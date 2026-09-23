using System.Runtime.CompilerServices;
using System.Text.Json;
using Godot;
using MegaCrit.Sts2.Core.Events.Custom.CrystalSphereEvent;
using MegaCrit.Sts2.Core.Events.Custom.CrystalSphereEvent.CrystalSphereItems;
using MegaCrit.Sts2.Core.Nodes.Events.Custom.CrystalSphere;
using MegaCrit.Sts2.Core.Nodes.Screens.Map;
using MegaCrit.Sts2.Core.Nodes.Screens.Overlays;
using sts2_headless.sts2_headlessCode.Models;
using ToolType = MegaCrit.Sts2.Core.Events.Custom.CrystalSphereEvent.CrystalSphereMinigame.CrystalSphereToolType;

namespace sts2_headless.sts2_headlessCode.Server.Handlers;

/// <summary>
/// The Crystal Sphere event's Divination minigame: an 11x11 fogged grid
/// with items hidden under it. Each divination uncovers a 3x3 area ("big")
/// or one cell ("small"); an item is won once all of its cells are
/// uncovered. The game draws it as a custom overlay, so the regular event
/// handling can't see or play it.
/// </summary>
public static class CrystalSphereHandler
{
    private static readonly JsonSerializerOptions JsonOptions = new() { WriteIndented = true };

    /// <summary>
    /// The minigame screen, when it's what the player is looking at. After
    /// its proceed the map opens but the screen can linger in the overlay
    /// stack (AutoSlay removes it by hand), so an open map means it's done.
    /// </summary>
    internal static NCrystalSphereScreen? ActiveScreen()
    {
        if (NOverlayStack.Instance?.Peek() is not NCrystalSphereScreen screen)
            return null;
        if (!GodotObject.IsInstanceValid(screen) || NMapScreen.Instance?.IsOpen == true)
            return null;
        return screen;
    }

    internal static CrystalSphereInfo BuildInfo(NCrystalSphereScreen screen)
    {
        var game = screen._entity;
        int width = game.GridSize.X;
        int height = game.GridSize.Y;
        var labels = LabelVisibleItems(game);

        var grid = new List<string>(height);
        for (int y = 0; y < height; y++)
        {
            var row = new char[width];
            for (int x = 0; x < width; x++)
            {
                var cell = game.cells[x, y];
                row[x] = cell.IsHidden ? '#' : cell.Item is null ? '.' : labels[cell.Item];
            }
            grid.Add(new string(row));
        }

        return new CrystalSphereInfo
        {
            Width = width,
            Height = height,
            DivinationsLeft = game.DivinationCount,
            CanProceed = screen._proceedButton?.IsEnabled == true,
            Grid = grid,
            Items = labels
                .OrderBy(kv => kv.Value)
                .ToDictionary(kv => kv.Value.ToString(), kv => Describe(kv.Key).Type)
        };
    }

    // Per-board item labels, kept for the board's lifetime so a label keeps
    // meaning the same item from one read to the next.
    private static readonly ConditionalWeakTable<CrystalSphereMinigame, Dictionary<CrystalSphereItem, char>> Labels = new();

    /// <summary>
    /// Give every item with an uncovered cell its own letter, in the order
    /// items first come into view (row by row). Distinct letters tell
    /// touching items of the same type apart, as their art does in game.
    /// Labelling by the game's item order instead would leak type and
    /// rarity (the relic is always item 0).
    /// </summary>
    private static Dictionary<CrystalSphereItem, char> LabelVisibleItems(CrystalSphereMinigame game)
    {
        var labels = Labels.GetOrCreateValue(game);
        for (int y = 0; y < game.GridSize.Y; y++)
        {
            for (int x = 0; x < game.GridSize.X; x++)
            {
                var cell = game.cells[x, y];
                if (!cell.IsHidden && cell.Item is { } item && !labels.ContainsKey(item))
                    labels[item] = (char)('A' + labels.Count);
            }
        }
        return labels;
    }

    /// <summary>
    /// Spend one divination: pick the tool, then uncover around (x, y).
    /// Returns once the uncovering (and, on the last divination, the reward
    /// hand-out) has played out.
    /// </summary>
    internal static async Task<string> Divine(CombatActionRequest request)
    {
        var screen = ActiveScreen();
        if (screen is null)
            return Error("Not on the Crystal Sphere screen.");
        // The tool buttons are wired up in _Ready.
        if (!screen.IsNodeReady())
            return Error("The Crystal Sphere screen is still opening; retry in a moment.");

        var game = screen._entity;
        if (game.DivinationCount <= 0)
            return Error("No divinations left. Claim any rewards, then proceed.");

        if (request.X is null || request.Y is null)
            return Error("crystal_sphere_divine requires x and y.");
        int x = request.X.Value;
        int y = request.Y.Value;
        if (x < 0 || x >= game.GridSize.X || y < 0 || y >= game.GridSize.Y)
            return Error($"({x}, {y}) is off the grid (0-{game.GridSize.X - 1}, 0-{game.GridSize.Y - 1}).");

        ToolType tool;
        switch (request.Tool?.Trim().ToLowerInvariant())
        {
            case "big": tool = ToolType.Big; break;
            case "small": tool = ToolType.Small; break;
            default: return Error("crystal_sphere_divine requires tool: \"big\" (3x3 around the cell) or \"small\" (the cell only).");
        }

        // The game spends the divination even when nothing is left to
        // uncover; refuse that instead of wasting it.
        var area = Area(tool, x, y, game.GridSize);
        if (!area.Any(c => game.cells[c.X, c.Y].IsHidden))
            return Error($"Divining ({x}, {y}) with the {request.Tool} tool would uncover nothing; every cell there is already clear.");

        // Switch tools through the screen's own handlers so its buttons show
        // the right one, as clicking them would.
        if (tool == ToolType.Big)
            screen.SetBigDivination(screen._bigDivinationButton);
        else
            screen.SetSmallDivination(screen._smallDivinationButton);

        var revealedBefore = RevealedIds(game);
        await game.CellClicked(game.cells[x, y]);

        // The last divination hands out the rewards after a short pause, as
        // a rewards overlay on top of this screen (none when nothing was won,
        // in which case proceed enables straight away).
        if (game.DivinationCount == 0)
        {
            await WaitUntil(() => !ReferenceEquals(NOverlayStack.Instance?.Peek(), screen)
                                  || screen._proceedButton?.IsEnabled == true, 10000);
        }

        var labels = LabelVisibleItems(game);
        var newlyRevealed = RevealedIds(game).Except(revealedBefore)
            .Select(id => game.Items[id])
            .Select(item => (Label: labels[item], Desc: Describe(item)))
            .OrderBy(r => r.Label)
            .Select(r => $"{r.Label} ({(r.Desc.Variant is null ? r.Desc.Type : $"{r.Desc.Variant} {r.Desc.Type}")})")
            .ToList();
        string found = newlyRevealed.Count > 0 ? $" Revealed: {string.Join(", ", newlyRevealed)}." : "";
        return Success($"Divined ({x}, {y}) with the {request.Tool!.Trim().ToLowerInvariant()} tool. " +
                       $"{game.DivinationCount} divination(s) left.{found}");
    }

    /// <summary>
    /// Leave the finished minigame for the map.
    /// </summary>
    internal static async Task<string> Proceed(NCrystalSphereScreen screen)
    {
        if (screen._proceedButton?.IsEnabled != true)
        {
            return Error(screen._entity.DivinationCount > 0
                ? $"{screen._entity.DivinationCount} divination(s) left; use crystal_sphere_divine first."
                : "The Crystal Sphere is still handing out rewards; re-read the state.");
        }

        screen._proceedButton.ForceClick();
        await WaitUntil(() => NMapScreen.Instance?.IsOpen == true, 10000);

        // Same cleanup AutoSlay does: the map can open with this screen still
        // on the overlay stack.
        if (GodotObject.IsInstanceValid(screen) && ReferenceEquals(NOverlayStack.Instance?.Peek(), screen))
            NOverlayStack.Instance!.Remove(screen);

        return Success("Proceeded from the Crystal Sphere.");
    }

    private static List<Vector2I> Area(ToolType tool, int x, int y, Vector2I size)
    {
        var cells = new List<Vector2I>();
        int reach = tool == ToolType.Big ? 1 : 0;
        for (int dx = -reach; dx <= reach; dx++)
            for (int dy = -reach; dy <= reach; dy++)
            {
                int cx = x + dx, cy = y + dy;
                if (cx >= 0 && cx < size.X && cy >= 0 && cy < size.Y)
                    cells.Add(new Vector2I(cx, cy));
            }
        return cells;
    }

    private static HashSet<int> RevealedIds(CrystalSphereMinigame game)
    {
        var ids = new HashSet<int>();
        for (int id = 0; id < game.Items.Count; id++)
        {
            var item = game.Items[id];
            bool all = true;
            for (int dx = 0; dx < item.Size.X && all; dx++)
                for (int dy = 0; dy < item.Size.Y && all; dy++)
                    all = !game.cells[item.Position.X + dx, item.Position.Y + dy].IsHidden;
            if (all)
                ids.Add(id);
        }
        return ids;
    }

    private static (string Type, string? Variant) Describe(CrystalSphereItem item) => item switch
    {
        CrystalSphereRelic => ("relic", null),
        CrystalSpherePotion potion => ("potion", potion._rarity.ToString().ToLowerInvariant()),
        CrystalSphereCardReward card => ("card reward", card._rarity.ToString().ToLowerInvariant()),
        CrystalSphereGold gold => ("gold", gold._isBig ? "big" : "small"),
        CrystalSphereCurse => ("curse", null),
        _ => (item.GetType().Name, null)
    };

    private static async Task<bool> WaitUntil(Func<bool> condition, int timeoutMs)
    {
        for (int waited = 0; waited < timeoutMs; waited += 50)
        {
            if (condition())
                return true;
            await Task.Delay(50);
        }
        return condition();
    }

    private static string Success(string message)
    {
        return JsonSerializer.Serialize(new ActionResponse { Success = true, Message = message }, JsonOptions);
    }

    private static string Error(string error)
    {
        return JsonSerializer.Serialize(new ActionResponse { Success = false, Error = error }, JsonOptions);
    }
}

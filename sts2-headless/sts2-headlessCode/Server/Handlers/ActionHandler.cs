using System.Text.Json;
using Godot;
using MegaCrit.Sts2.Core.Commands;
using MegaCrit.Sts2.Core.Entities.Merchant;
using MegaCrit.Sts2.Core.Map;
using MegaCrit.Sts2.Core.Nodes;
using MegaCrit.Sts2.Core.Nodes.Cards.Holders;
using MegaCrit.Sts2.Core.Nodes.CommonUi;
using MegaCrit.Sts2.Core.Nodes.Events;
using MegaCrit.Sts2.Core.Nodes.GodotExtensions;
using MegaCrit.Sts2.Core.Nodes.RestSite;
using MegaCrit.Sts2.Core.Nodes.Rewards;
using MegaCrit.Sts2.Core.Nodes.Rooms;
using MegaCrit.Sts2.Core.Nodes.Screens;
using MegaCrit.Sts2.Core.Nodes.Screens.CardSelection;
using MegaCrit.Sts2.Core.Nodes.Screens.Map;
using MegaCrit.Sts2.Core.Nodes.Screens.Overlays;
using MegaCrit.Sts2.Core.Nodes.Screens.Shops;
using MegaCrit.Sts2.Core.Rooms;
using MegaCrit.Sts2.Core.Runs;
using sts2_headless.sts2_headlessCode.Models;

namespace sts2_headless.sts2_headlessCode.Server.Handlers;

public static class ActionHandler
{
    private static readonly JsonSerializerOptions JsonOptions = new() { WriteIndented = true };

    public static async Task<string> HandleAction(string requestBody)
    {
        CombatActionRequest? request;
        try
        {
            request = JsonSerializer.Deserialize<CombatActionRequest>(requestBody);
        }
        catch (JsonException)
        {
            return Error("Invalid JSON in request body.");
        }

        if (request is null || string.IsNullOrEmpty(request.Type))
            return Error("Missing required field: type");

        var run = NRun.Instance;
        if (run is null)
            return Error("No active run.");

        return request.Type switch
        {
            "choose_map_node" => ChooseMapNode(request, run),
            "choose_event_option" => ChooseEventOption(request, run),
            "claim_reward" => ClaimReward(request),
            "proceed" => Proceed(run),
            "choose_rest_option" => ChooseRestOption(request, run),
            "choose_card_reward" => ChooseCardReward(request),
            "skip_card_reward" => SkipCardReward(),
            "shop_buy" => ShopBuy(request, run),
            "shop_remove_card" => ShopRemoveCard(request, run),
            "shop_leave" => ShopLeave(run),
            "select_card" => SelectCard(request),
            "confirm_selection" => await ConfirmSelection(),
            _ => Error($"Unknown action type: {request.Type}")
        };
    }

    private static string ChooseMapNode(CombatActionRequest request, NRun run)
    {
        if (request.Col is null || request.Row is null)
            return Error("choose_map_node requires col and row.");

        int col = request.Col.Value;
        int row = request.Row.Value;

        var mapScreen = NMapScreen.Instance;
        if (mapScreen is null)
            return Error("Map screen not available.");

        var mapPoints = FindAll<NMapPoint>(mapScreen);
        var target = mapPoints.FirstOrDefault(mp => mp.Point.coord.col == col && mp.Point.coord.row == row);

        if (target is null)
            return Error($"Map point ({col}, {row}) not found.");

        target.ForceClick();
        return Success($"Selected map node ({col}, {row})");
    }

    private static string ChooseEventOption(CombatActionRequest request, NRun run)
    {
        if (request.CardIndex is null)
            return Error("choose_event_option requires card_index (option index).");

        int optionIndex = request.CardIndex.Value;

        var root = ((SceneTree)Engine.GetMainLoop()).Root;
        var eventRoom = root.GetNodeOrNull("/root/Game/RootSceneContainer/Run/RoomContainer/EventRoom");
        if (eventRoom is null)
            return Error("Not in an event room.");

        var buttons = FindAll<NEventOptionButton>(eventRoom)
            .Where(b => !b.Option.IsLocked)
            .ToList();

        if (optionIndex < 0 || optionIndex >= buttons.Count)
            return Error($"Option index {optionIndex} out of range ({buttons.Count} options).");

        buttons[optionIndex].ForceClick();
        return Success($"Selected event option {optionIndex}");
    }

    private static string ClaimReward(CombatActionRequest request)
    {
        if (request.CardIndex is null)
            return Error("claim_reward requires card_index (reward index).");

        int rewardIndex = request.CardIndex.Value;

        var overlay = NOverlayStack.Instance?.Peek();
        if (overlay is not NRewardsScreen rewardsScreen)
            return Error("Not on rewards screen.");

        var buttons = FindAll<NRewardButton>(rewardsScreen)
            .Where(b => b.IsEnabled)
            .ToList();

        if (rewardIndex < 0 || rewardIndex >= buttons.Count)
            return Error($"Reward index {rewardIndex} out of range ({buttons.Count} rewards).");

        buttons[rewardIndex].ForceClick();
        return Success($"Claimed reward {rewardIndex}");
    }

    private static string Proceed(NRun run)
    {
        // Try rewards screen proceed button first
        var overlay = NOverlayStack.Instance?.Peek();
        if (overlay is NRewardsScreen rewardsScreen)
        {
            var proceedBtn = FindFirst<NProceedButton>(rewardsScreen);
            if (proceedBtn is not null)
            {
                proceedBtn.ForceClick();
                return Success("Proceeded from rewards screen.");
            }
        }

        // Try rest site proceed
        var root = ((SceneTree)Engine.GetMainLoop()).Root;
        var restRoom = root.GetNodeOrNull<NRestSiteRoom>(
            "/root/Game/RootSceneContainer/Run/RoomContainer/RestSiteRoom");
        if (restRoom is not null)
        {
            var proceedBtn = restRoom.ProceedButton;
            if (proceedBtn is not null && proceedBtn.IsEnabled)
            {
                proceedBtn.ForceClick();
                return Success("Proceeded from rest site.");
            }
        }

        // Try merchant room proceed
        var merchantRoom = root.GetNodeOrNull<NMerchantRoom>(
            "/root/Game/RootSceneContainer/Run/RoomContainer/MerchantRoom");
        if (merchantRoom is not null)
        {
            merchantRoom.ProceedButton?.ForceClick();
            return Success("Proceeded from shop.");
        }

        // Try event proceed
        var eventRoom = root.GetNodeOrNull("/root/Game/RootSceneContainer/Run/RoomContainer/EventRoom");
        if (eventRoom is not null)
        {
            var proceedButtons = FindAll<NEventOptionButton>(eventRoom)
                .Where(b => b.Option.IsProceed && !b.Option.IsLocked)
                .ToList();
            if (proceedButtons.Count > 0)
            {
                proceedButtons[0].ForceClick();
                return Success("Proceeded from event.");
            }
        }

        return Error("No proceed button found on current screen.");
    }

    private static string ChooseRestOption(CombatActionRequest request, NRun run)
    {
        if (request.CardIndex is null)
            return Error("choose_rest_option requires card_index (option index).");

        int optionIndex = request.CardIndex.Value;

        var root = ((SceneTree)Engine.GetMainLoop()).Root;
        var restRoom = root.GetNodeOrNull<NRestSiteRoom>(
            "/root/Game/RootSceneContainer/Run/RoomContainer/RestSiteRoom");
        if (restRoom is null)
            return Error("Not at a rest site.");

        var buttons = FindAll<NRestSiteButton>(restRoom)
            .Where(b => b.Option.IsEnabled)
            .ToList();

        if (optionIndex < 0 || optionIndex >= buttons.Count)
            return Error($"Option index {optionIndex} out of range ({buttons.Count} options).");

        buttons[optionIndex].ForceClick();
        return Success($"Selected rest option {optionIndex}");
    }

    private static string ChooseCardReward(CombatActionRequest request)
    {
        if (request.CardIndex is null)
            return Error("choose_card_reward requires card_index.");

        int cardIndex = request.CardIndex.Value;

        var overlay = NOverlayStack.Instance?.Peek();
        if (overlay is not NCardRewardSelectionScreen cardScreen)
            return Error("Not on card reward screen.");

        var holders = FindAll<NCardHolder>(cardScreen);
        if (cardIndex < 0 || cardIndex >= holders.Count)
            return Error($"Card index {cardIndex} out of range ({holders.Count} cards).");

        holders[cardIndex].EmitSignal(NCardHolder.SignalName.Pressed, holders[cardIndex]);
        return Success($"Selected card reward {cardIndex}");
    }

    private static string SkipCardReward()
    {
        var overlay = NOverlayStack.Instance?.Peek();
        if (overlay is not NCardRewardSelectionScreen cardScreen)
            return Error("Not on card reward screen.");

        // The card reward screen's completion source expects (empty holders, removeReward=true) to skip
        cardScreen._completionSource?.TrySetResult(
            new Tuple<IEnumerable<NCardHolder>, bool>(Array.Empty<NCardHolder>(), true));
        return Success("Skipped card reward.");
    }

    private static string ShopBuy(CombatActionRequest request, NRun run)
    {
        if (request.CardIndex is null)
            return Error("shop_buy requires card_index (slot index).");

        int slotIndex = request.CardIndex.Value;
        var state = run._state;

        if (state.CurrentRoom is not MerchantRoom merchantRoom)
            return Error("Not in a shop.");

        var inventory = merchantRoom.Inventory;
        var allEntries = inventory.AllEntries.Where(e => e.IsStocked).ToList();

        if (slotIndex < 0 || slotIndex >= allEntries.Count)
            return Error($"Slot index {slotIndex} out of range ({allEntries.Count} stocked items).");

        var entry = allEntries[slotIndex];
        if (!entry.EnoughGold)
            return Error($"Not enough gold (need {entry.Cost}).");

        _ = entry.OnTryPurchaseWrapper(inventory);
        return Success($"Purchased item at index {slotIndex} (cost: {entry.Cost})");
    }

    private static string ShopRemoveCard(CombatActionRequest request, NRun run)
    {
        var state = run._state;
        if (state.CurrentRoom is not MerchantRoom merchantRoom)
            return Error("Not in a shop.");

        var removal = merchantRoom.Inventory.CardRemovalEntry;
        if (removal is null || !removal.IsStocked)
            return Error("Card removal not available.");

        if (!removal.EnoughGold)
            return Error($"Not enough gold for card removal (need {removal.Cost}).");

        _ = removal.OnTryPurchaseWrapper(merchantRoom.Inventory);
        return Success($"Opening card removal (cost: {removal.Cost})");
    }

    private static string ShopLeave(NRun run)
    {
        var root = ((SceneTree)Engine.GetMainLoop()).Root;
        var merchantRoom = root.GetNodeOrNull<NMerchantRoom>(
            "/root/Game/RootSceneContainer/Run/RoomContainer/MerchantRoom");
        if (merchantRoom is null)
            return Error("Not in a shop.");

        merchantRoom.ProceedButton?.ForceClick();
        return Success("Left shop.");
    }

    private static string SelectCard(CombatActionRequest request)
    {
        if (request.CardIndex is null)
            return Error("select_card requires card_index.");

        int cardIndex = request.CardIndex.Value;

        var overlay = NOverlayStack.Instance?.Peek();
        if (overlay is null)
            return Error("No overlay screen.");

        var node = (Node)overlay;

        // Handle bundle selection screens (e.g. Scroll Boxes — pick between card packs)
        if (overlay is NChooseABundleSelectionScreen)
        {
            var bundles = FindAll<MegaCrit.Sts2.Core.Nodes.Cards.NCardBundle>(node);
            if (cardIndex < 0 || cardIndex >= bundles.Count)
                return Error($"card_index {cardIndex} out of range ({bundles.Count} bundles).");

            bundles[cardIndex].Hitbox.ForceClick();
            return Success($"Selected bundle {cardIndex}");
        }

        // Handle card grid selection screens (upgrade, transform, remove, etc.)
        if (overlay is NCardGridSelectionScreen)
        {
            var holders = FindAll<NGridCardHolder>(node);
            if (cardIndex < 0 || cardIndex >= holders.Count)
                return Error($"card_index {cardIndex} out of range ({holders.Count} cards).");

            holders[cardIndex].EmitSignal(NCardHolder.SignalName.Pressed, holders[cardIndex]);
            return Success($"Selected card {cardIndex}");
        }

        // Handle choose-a-card screens
        if (overlay is NChooseACardSelectionScreen)
        {
            var holders = FindAll<NGridCardHolder>(node);
            if (cardIndex < 0 || cardIndex >= holders.Count)
                return Error($"card_index {cardIndex} out of range ({holders.Count} cards).");

            holders[cardIndex].EmitSignal(NCardHolder.SignalName.Pressed, holders[cardIndex]);
            return Success($"Selected card {cardIndex}");
        }

        return Error($"Unknown overlay screen type: {overlay.GetType().Name}");
    }

    private static async Task<string> ConfirmSelection()
    {
        var overlay = NOverlayStack.Instance?.Peek();
        if (overlay is null)
            return Error("No overlay screen.");

        var node = (Node)overlay;

        // Strategy: find all NConfirmButton nodes, click them in sequence
        // Some screens need two clicks (first opens preview, second confirms)
        // Keep clicking enabled confirm buttons until the screen closes
        for (int round = 0; round < 3; round++)
        {
            // Wait for a confirm button to become visible and enabled
            NConfirmButton? btn = null;
            for (int i = 0; i < 40; i++) // up to 2 seconds per round
            {
                if (!GodotObject.IsInstanceValid(node) || !(node as Control)!.IsVisibleInTree())
                    return Success("Confirmed selection.");

                var allBtns = FindAll<NConfirmButton>(node);
                btn = allBtns.FirstOrDefault(b => b.Visible && b.IsEnabled);
                if (btn is not null)
                    break;
                await Task.Delay(50);
            }

            if (btn is null)
            {
                // No confirm button found — screen might have already closed
                if (!GodotObject.IsInstanceValid(node) || !(node as Control)!.IsVisibleInTree())
                    return Success("Confirmed selection.");
                return Error("No enabled confirm button found.");
            }

            btn.ForceClick();
            await Task.Delay(300); // let animations play
        }

        // Final wait for screen to close
        for (int i = 0; i < 40; i++)
        {
            if (!GodotObject.IsInstanceValid(node) || !(node as Control)!.IsVisibleInTree())
                break;
            await Task.Delay(50);
        }

        return Success("Confirmed selection.");
    }

    // Godot node search helpers (same pattern as AutoSlay's UiHelper)
    public static List<T> FindAll<T>(Node start) where T : Node
    {
        var found = new List<T>();
        if (GodotObject.IsInstanceValid(start))
            FindAllRecursive(start, found);
        return found;
    }

    private static void FindAllRecursive<T>(Node node, List<T> found) where T : Node
    {
        if (!GodotObject.IsInstanceValid(node)) return;
        if (node is T item) found.Add(item);
        foreach (var child in node.GetChildren())
            FindAllRecursive(child, found);
    }

    private static T? FindFirst<T>(Node start) where T : Node
    {
        if (!GodotObject.IsInstanceValid(start)) return null;
        if (start is T result) return result;
        foreach (var child in start.GetChildren())
        {
            var found = FindFirst<T>(child);
            if (found is not null) return found;
        }
        return null;
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

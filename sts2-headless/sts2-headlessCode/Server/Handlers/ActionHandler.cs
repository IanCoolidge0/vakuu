using System.Text.Json;
using Godot;
using MegaCrit.Sts2.Core.Combat;
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
using MegaCrit.Sts2.Core.Nodes.Screens.TreasureRoomRelic;
using MegaCrit.Sts2.Core.Rewards;
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

        if (StateHandler.IsRunOver(run._state))
            return Error(CombatActionHandler.RunOverMessage(run._state));

        // Every action waits for its effect to land before returning, so the
        // next /game/state shows the outcome rather than the screen mid-
        // animation. Actions without a dedicated wait use Settled, which
        // waits for any observable state change.
        return request.Type switch
        {
            "choose_map_node" => await ChooseMapNode(request, run),
            "choose_event_option" => await ChooseEventOption(request, run),
            "claim_reward" => await Settled(run, () => ClaimReward(request, run)),
            "skip_rewards" => await Settled(run, SkipRewards),
            "proceed" => await Proceed(run),
            "choose_rest_option" => await ChooseRestOption(request, run),
            "choose_card_reward" => await Settled(run, () => ChooseCardReward(request)),
            "skip_card_reward" => await Settled(run, SkipCardReward),
            "shop_buy" => await Settled(run, () => ShopBuy(request, run)),
            "shop_remove_card" => await Settled(run, () => ShopRemoveCard(request, run)),
            "select_card" => SelectCard(request),
            "confirm_selection" => await ConfirmSelection(),
            "open_chest" => await Settled(run, OpenChest),
            "pick_relic" => await Settled(run, () => PickRelic(request)),
            _ => Error($"Unknown action type: {request.Type}")
        };
    }

    private const string EventRoomPath = "/root/Game/RootSceneContainer/Run/RoomContainer/EventRoom";
    private const int PollIntervalMs = 50;

    private static async Task<string> ChooseMapNode(CombatActionRequest request, NRun run)
    {
        if (request.Col is null || request.Row is null)
            return Error("choose_map_node requires col and row.");

        int col = request.Col.Value;
        int row = request.Row.Value;

        var mapScreen = NMapScreen.Instance;
        if (mapScreen is null || !mapScreen.IsOpen)
            return Error($"The map is not open (current screen: {StateHandler.CurrentScreen()}). " +
                         "Finish the current screen first, usually with proceed.");

        NMapPoint? FindTarget() => FindAll<NMapPoint>(mapScreen)
            .FirstOrDefault(mp => mp.Point.coord.col == col && mp.Point.coord.row == row);

        var target = FindTarget();
        if (target is null)
            return Error($"Map point ({col}, {row}) not found.");

        // A finished event can leave its proceed button pending, often
        // invisible, while the map is already showing. It swallows map
        // clicks, so a click "succeeds" and nothing happens. Only a finished
        // event can be in this state (a live one is reported as the event
        // screen), so closing it is what the player would do anyway.
        string note = "";
        if (!target.IsTravelable && await DismissFinishedEvent(mapScreen))
        {
            note = " (closed the finished event that was still open)";
            target = FindTarget() ?? target;
        }

        if (!target.IsTravelable)
        {
            var reachable = FindAll<NMapPoint>(mapScreen)
                .Where(mp => mp.IsTravelable)
                .Select(mp => $"({mp.Point.coord.col}, {mp.Point.coord.row})")
                .ToList();
            return Error(reachable.Count > 0
                ? $"Map node ({col}, {row}) is not reachable from here. Reachable nodes: {string.Join(", ", reachable)}."
                : "No map node can be selected right now; the game may still be transitioning. Re-read the state.");
        }

        var state = run._state;
        var coordBefore = state.CurrentMapCoord;
        bool wasTraveling = mapScreen.IsTraveling;

        // What NMapPoint.OnRelease calls once its UI gates pass. The gates
        // beyond IsTravelable (checked above) are UI-only — the first-map
        // tutorial gate on row 0 (the ancient), map drawing mode, controller
        // focus — and can silently swallow a click.
        mapScreen.OnMapPointSelectedLocally(target);

        // The click only casts a map vote; travel starts once the action
        // queue processes it. No sign of travel means the click was lost.
        bool started = await WaitUntil(
            () => (!wasTraveling && mapScreen.IsTraveling) || !Equals(state.CurrentMapCoord, coordBefore),
            3000);
        if (!started)
            return Error($"Clicking map node ({col}, {row}) had no effect. Re-read the state before retrying.");

        bool arrived = await WaitUntil(
            () => state.CurrentMapCoord is { } c && c.col == col && c.row == row
                  && NMapScreen.Instance?.IsOpen != true,
            15000);
        if (!arrived)
            return Error($"Travel to ({col}, {row}) started but hadn't finished after 15s. Re-read the state.");

        await WaitForScreenReady(15000);
        return Success($"Selected map node ({col}, {row}){note}");
    }

    /// <summary>
    /// Click the pending proceed button of a finished event, if there is
    /// one, and wait for the map to accept travel. Returns whether a button
    /// was clicked.
    /// </summary>
    private static async Task<bool> DismissFinishedEvent(NMapScreen mapScreen)
    {
        var root = ((SceneTree)Engine.GetMainLoop()).Root;
        var eventRoom = root.GetNodeOrNull(EventRoomPath);
        if (eventRoom is null)
            return false;

        var proceed = FindAll<NEventOptionButton>(eventRoom)
            .FirstOrDefault(b => b.Option.IsProceed && !b.Option.IsLocked);
        if (proceed is null)
            return false;

        proceed.ForceClick();
        await WaitUntil(() => FindAll<NMapPoint>(mapScreen).Any(mp => mp.IsTravelable), 5000);
        return true;
    }

    private static async Task<string> ChooseEventOption(CombatActionRequest request, NRun run)
    {
        if (request.CardIndex is null)
            return Error("choose_event_option requires card_index (option index).");

        int optionIndex = request.CardIndex.Value;

        var state = run._state;
        if (state.CurrentRoom is not EventRoom room)
            return Error("Not in an event room.");

        // Index into the model's options, the same numbering /game/state
        // reports (locked options included), then click that option's own
        // button. Indexing a filtered button list instead shifts every index
        // after a locked option onto the wrong choice.
        var eventModel = room.LocalMutableEvent;
        var options = eventModel.CurrentOptions;
        if (optionIndex < 0 || optionIndex >= options.Count)
            return Error($"Option index {optionIndex} out of range ({options.Count} options).");

        var option = options[optionIndex];
        if (option.IsLocked)
            return Error($"Option {optionIndex} is locked.");

        var root = ((SceneTree)Engine.GetMainLoop()).Root;
        var eventNode = root.GetNodeOrNull(EventRoomPath);
        var button = eventNode is null
            ? null
            : FindAll<NEventOptionButton>(eventNode).FirstOrDefault(b => b.Option == option);
        if (button is null)
            return Error("That option's button isn't on screen yet (the event is still animating). Re-read the state and retry.");

        var optionsBefore = options.ToList();
        var overlayBefore = NOverlayStack.Instance?.Peek();
        bool mapWasOpen = NMapScreen.Instance?.IsOpen == true;

        button.ForceClick();

        // Options resolve asynchronously, and costs land before the next
        // page is set: Colossal Flower takes the HP immediately but swaps in
        // its next options after an animation. Returning early shows the new
        // HP next to the old options, and the next pick goes in blind. Wait
        // until the event has visibly moved on.
        bool moved = await WaitUntil(
            () => StateHandler.IsRunOver(state)
                  || state.CurrentRoom != room
                  || eventModel.IsFinished
                  || !optionsBefore.SequenceEqual(eventModel.CurrentOptions)
                  || !ReferenceEquals(NOverlayStack.Instance?.Peek(), overlayBefore)
                  || (!mapWasOpen && NMapScreen.Instance?.IsOpen == true)
                  || CombatManager.Instance.IsInProgress,
            15000);
        if (!moved)
            return Success($"Selected event option {optionIndex} (no change observed yet; re-read the state)");

        await WaitForScreenReady(10000);
        return Success($"Selected event option {optionIndex}");
    }

    private static string ClaimReward(CombatActionRequest request, NRun run)
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

        // With every slot full the game refuses the potion and leaves the
        // reward in place, so the click would look like it did nothing.
        var player = run._state.Players.FirstOrDefault();
        if (buttons[rewardIndex].Reward is PotionReward
            && player is not null && player.PotionSlots.All(p => p is not null))
            return Error("Potion slots are full, so this potion can't be taken. " +
                         "Claim the other rewards, then leave it with skip_rewards.");

        buttons[rewardIndex].ForceClick();
        return Success($"Claimed reward {rewardIndex}");
    }

    private static string SkipRewards()
    {
        var overlay = NOverlayStack.Instance?.Peek();
        if (overlay is not NRewardsScreen rewardsScreen)
            return Error("Not on rewards screen.");

        var proceedBtn = rewardsScreen._proceedButton
                         ?? FindFirst<NProceedButton>(rewardsScreen);
        if (proceedBtn is null)
            return Error("Rewards proceed/skip button not found.");
        if (!proceedBtn.IsEnabled)
            return Error("Skipping is not allowed for this rewards screen.");

        int unclaimed = rewardsScreen._rewardButtons
            .Except(rewardsScreen._skippedRewardButtons)
            .Count();
        proceedBtn.ForceClick();
        return Success(unclaimed > 0
            ? $"Left rewards screen, forfeiting {unclaimed} unclaimed reward(s)."
            : "Left rewards screen.");
    }

    private static async Task<string> Proceed(NRun run)
    {
        string screenBefore = StateHandler.CurrentScreen();
        string result = ClickProceed(run);
        if (!IsSuccess(result))
            return result;

        await WaitUntil(() =>
        {
            string screen = StateHandler.CurrentScreen();
            return screen != screenBefore && screen is not ("waiting" or "unknown");
        }, 10000);
        await WaitForScreenReady(10000);
        return result;
    }

    private static string ClickProceed(NRun run)
    {
        // Try rewards screen proceed button first
        var overlay = NOverlayStack.Instance?.Peek();
        if (overlay is NRewardsScreen rewardsScreen)
        {
            // The rewards screen's button doubles as "Skip" while unclaimed
            // rewards remain — clicking it then forfeits them (the boss
            // branch of OnProceedButtonPressed advances the act with no
            // skip-guard at all). Refuse instead of force-clicking; the
            // explicit skip_rewards action exists for deliberate forfeits.
            int unclaimed = rewardsScreen._rewardButtons
                .Except(rewardsScreen._skippedRewardButtons)
                .Count();
            if (unclaimed > 0)
                return Error($"{unclaimed} unclaimed reward(s) remain — proceeding now would forfeit them. " +
                             "Use claim_reward to take them, or skip_rewards to forfeit deliberately.");

            var proceedBtn = rewardsScreen._proceedButton
                             ?? FindFirst<NProceedButton>(rewardsScreen);
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
            var proceedBtn = merchantRoom.ProceedButton;
            if (proceedBtn is not null && proceedBtn.IsEnabled)
            {
                proceedBtn.ForceClick();
                return Success("Proceeded from shop.");
            }
        }

        // Try treasure room proceed
        var treasureRoom = root.GetNodeOrNull<NTreasureRoom>(
            "/root/Game/RootSceneContainer/Run/RoomContainer/TreasureRoom");
        if (treasureRoom is not null)
        {
            var proceedBtn = treasureRoom.ProceedButton;
            if (proceedBtn is not null && proceedBtn.IsEnabled)
            {
                proceedBtn.ForceClick();
                return Success("Proceeded from treasure room.");
            }
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

    private static async Task<string> ChooseRestOption(CombatActionRequest request, NRun run)
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

        var overlayBefore = NOverlayStack.Instance?.Peek();
        buttons[optionIndex].ForceClick();

        // Rest, Lift and the like play out before the rest site enables its
        // proceed button; Smith opens the upgrade grid instead. Wait for
        // either, or a proceed right after this returns finds no button.
        await WaitUntil(
            () => restRoom.ProceedButton?.IsEnabled == true
                  || !ReferenceEquals(NOverlayStack.Instance?.Peek(), overlayBefore),
            10000);
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

        // The card reward screen's completion source resolves to a selected
        // option index; null means the reward was skipped
        cardScreen._completionSource?.TrySetResult(null);
        return Success("Skipped card reward.");
    }

    private static string ShopBuy(CombatActionRequest request, NRun run)
    {
        var state = run._state;

        if (state.CurrentRoom is not MerchantRoom merchantRoom)
            return Error("Not in a shop.");

        // Purchase by name: flat slot indices shift when an item is bought
        // (everything after it renumbers), which made repeat purchases in
        // one visit land on the wrong item. Names are stable for the whole
        // shop visit.
        if (string.IsNullOrWhiteSpace(request.Name))
            return Error("shop_buy requires name (the item's name as listed in the shop).");

        var inventory = merchantRoom.GetLocalInventory();
        string wanted = request.Name.Trim();

        var stocked = new List<(string Name, MerchantEntry Entry)>();
        foreach (var entry in inventory.CardEntries)
        {
            if (!entry.IsStocked || entry.CreationResult is null) continue;
            var info = CombatHandler.BuildCardInfo(entry.CreationResult.Card);
            stocked.Add((info.Name + (info.Upgraded ? "+" : ""), entry));
        }
        foreach (var entry in inventory.RelicEntries)
        {
            if (!entry.IsStocked || entry.Model is null) continue;
            stocked.Add((entry.Model.Title?.GetFormattedText() ?? entry.Model.Id.ToString(), entry));
        }
        foreach (var entry in inventory.PotionEntries)
        {
            if (!entry.IsStocked || entry.Model is null) continue;
            stocked.Add((entry.Model.Title?.GetFormattedText() ?? entry.Model.Id.ToString(), entry));
        }

        var match = stocked.FirstOrDefault(s =>
            string.Equals(s.Name, wanted, StringComparison.OrdinalIgnoreCase));

        if (match.Entry is null)
            return Error($"'{wanted}' is not stocked. Available: " +
                         string.Join(", ", stocked.Select(s => s.Name)));

        if (!match.Entry.EnoughGold)
            return Error($"Not enough gold for {match.Name} (need {match.Entry.Cost}).");

        _ = match.Entry.OnTryPurchaseWrapper(inventory);
        return Success($"Purchased {match.Name} (cost: {match.Entry.Cost})");
    }

    private static string ShopRemoveCard(CombatActionRequest request, NRun run)
    {
        var state = run._state;
        if (state.CurrentRoom is not MerchantRoom merchantRoom)
            return Error("Not in a shop.");

        var inventory = merchantRoom.GetLocalInventory();
        var removal = inventory.CardRemovalEntry;
        if (removal is null || !removal.IsStocked)
            return Error("Card removal not available.");

        if (!removal.EnoughGold)
            return Error($"Not enough gold for card removal (need {removal.Cost}).");

        _ = removal.OnTryPurchaseWrapper(inventory);
        return Success($"Opening card removal (cost: {removal.Cost})");
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

    private static string OpenChest()
    {
        var root = ((SceneTree)Engine.GetMainLoop()).Root;
        var treasureRoom = root.GetNodeOrNull<NTreasureRoom>(
            "/root/Game/RootSceneContainer/Run/RoomContainer/TreasureRoom");
        if (treasureRoom is null)
            return Error("Not in a treasure room.");
        if (treasureRoom._hasChestBeenOpened)
            return Error("Chest is already open. Use pick_relic to take a relic, then proceed.");
        if (treasureRoom._chestButton is null)
            return Error("Chest button not found.");

        treasureRoom._chestButton.ForceClick();
        return Success("Opened the chest.");
    }

    private static string PickRelic(CombatActionRequest request)
    {
        var root = ((SceneTree)Engine.GetMainLoop()).Root;
        var treasureRoom = root.GetNodeOrNull<NTreasureRoom>(
            "/root/Game/RootSceneContainer/Run/RoomContainer/TreasureRoom");
        if (treasureRoom is null)
            return Error("Not in a treasure room.");
        if (!treasureRoom._hasChestBeenOpened)
            return Error("Chest is not open yet — call open_chest first.");
        if (!treasureRoom._isRelicCollectionOpen)
            return Error("Relic already claimed — proceed to leave the room.");

        var collection = treasureRoom._relicCollection;
        if (collection is null)
            return Error("Relic collection not available.");

        var holders = collection._holdersInUse;
        if (holders is null || holders.Count == 0)
            return Error("No relic holders in use.");

        // Default to index 0 (singleplayer always has 1 relic).
        int index = request.CardIndex ?? 0;
        if (index < 0 || index >= holders.Count)
            return Error($"index {index} out of range ({holders.Count} relics).");

        collection.PickRelic(holders[index]);
        return Success($"Picked relic at index {index}.");
    }

    // --- Settling ---
    // Handlers run on the main thread; awaiting Task.Delay yields back to the
    // game loop, so the game keeps animating while we poll.

    private static async Task<bool> WaitUntil(Func<bool> condition, int timeoutMs)
    {
        for (int waited = 0; waited < timeoutMs; waited += PollIntervalMs)
        {
            if (condition())
                return true;
            await Task.Delay(PollIntervalMs);
        }
        return condition();
    }

    /// <summary>
    /// Wait out transition screens. Entering combat reports "combat" as soon
    /// as the room loads, before the first turn starts, so also wait for the
    /// player's play phase.
    /// </summary>
    private static Task<bool> WaitForScreenReady(int timeoutMs)
    {
        return WaitUntil(() =>
        {
            string screen = StateHandler.CurrentScreen();
            if (screen is "waiting" or "unknown")
                return false;
            return screen != "combat" || CombatActionHandler.IsPlayPhase();
        }, timeoutMs);
    }

    /// <summary>
    /// Run a fire-and-forget action, then wait until its effect shows up in
    /// the observable state and holds still. Returns early on failure.
    /// </summary>
    private static async Task<string> Settled(NRun run, Func<string> action)
    {
        string before = Fingerprint(run);
        string result = action();
        if (!IsSuccess(result))
            return result;

        if (await WaitUntil(() => Fingerprint(run) != before, 3000))
        {
            // One change can be the first of several (claiming a card reward
            // opens the card screen a beat after the click). Settle once the
            // state reads the same twice in a row.
            string last = Fingerprint(run);
            for (int waited = 0; waited < 1500; waited += 100)
            {
                await Task.Delay(100);
                string now = Fingerprint(run);
                if (now == last)
                    break;
                last = now;
            }
        }
        await WaitForScreenReady(10000);
        return result;
    }

    /// <summary>
    /// Everything a reward, shop or treasure action can change: the screen,
    /// the top overlay, the player's resources, and the treasure chest.
    /// </summary>
    private static string Fingerprint(NRun run)
    {
        var player = run._state.Players.FirstOrDefault();
        var overlay = NOverlayStack.Instance?.Peek();
        int rewards = overlay is NRewardsScreen rewardsScreen ? rewardsScreen._rewardButtons.Count() : -1;

        var root = ((SceneTree)Engine.GetMainLoop()).Root;
        var treasure = root.GetNodeOrNull<NTreasureRoom>(
            "/root/Game/RootSceneContainer/Run/RoomContainer/TreasureRoom");
        string chest = treasure is null ? "-" : $"{treasure._hasChestBeenOpened}/{treasure._isRelicCollectionOpen}";

        return string.Join("|",
            StateHandler.CurrentScreen(),
            overlay is Node node ? node.GetInstanceId().ToString() : "none",
            rewards,
            chest,
            player?.Gold,
            player?.Creature.CurrentHp,
            player?.Creature.MaxHp,
            player?.Relics.Count,
            player?.Deck.Cards.Count,
            player is null ? "" : string.Join(",", player.PotionSlots.Select(p => p?.Id.ToString() ?? "-")));
    }

    private static bool IsSuccess(string result)
    {
        return JsonSerializer.Deserialize<ActionResponse>(result) is { Success: true };
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

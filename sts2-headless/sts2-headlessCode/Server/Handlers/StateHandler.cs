using System.Text.Json;
using Godot;
using MegaCrit.Sts2.Core.Models;
using MegaCrit.Sts2.Core.Nodes;
using MegaCrit.Sts2.Core.Nodes.Rewards;
using MegaCrit.Sts2.Core.Nodes.Screens;
using MegaCrit.Sts2.Core.Nodes.Cards.Holders;
using MegaCrit.Sts2.Core.Nodes.Screens.CardSelection;
using MegaCrit.Sts2.Core.Nodes.Screens.Map;
using MegaCrit.Sts2.Core.Nodes.Screens.Overlays;
using MegaCrit.Sts2.Core.Rewards;
using MegaCrit.Sts2.Core.Rooms;
using MegaCrit.Sts2.Core.Saves;
using MegaCrit.Sts2.Core.Nodes.Events;
using sts2_headless.sts2_headlessCode.Models;
using sts2_headless.sts2_headlessCode.Server;

namespace sts2_headless.sts2_headlessCode.Server.Handlers;

public static class StateHandler
{
    private static readonly JsonSerializerOptions JsonOptions = new() { WriteIndented = true };

    public static string GetGameState()
    {
        var run = NRun.Instance;
        if (run is null)
            return JsonSerializer.Serialize(new { error = "No active run" }, JsonOptions);

        var state = run._state;
        var player = state.Players.FirstOrDefault();
        if (player is null)
            return JsonSerializer.Serialize(new { error = "No player found" }, JsonOptions);

        string screen = DetectScreen(state, run);

        var relics = player.Relics.Select(r => new RelicInfo
        {
            Id = r.Id.ToString(),
            Name = r.Title?.GetFormattedText() ?? r.Id.ToString(),
            Description = CombatHandler.CleanDescription(r.DynamicDescription?.GetFormattedText() ?? ""),
            Counter = r.ShowCounter ? r.DisplayAmount : null
        }).ToList();

        var potions = new List<PotionSlotInfo>();
        for (int i = 0; i < player.PotionSlots.Count; i++)
        {
            var potion = player.PotionSlots[i];
            potions.Add(new PotionSlotInfo
            {
                Index = i,
                Id = potion?.Id.ToString(),
                Name = potion?.Title?.GetFormattedText()
            });
        }

        var response = new GameStateResponse
        {
            Screen = screen,
            Character = player.Character.Title?.GetFormattedText() ?? player.Character.Id.ToString(),
            Ascension = state.AscensionLevel,
            Act = state.CurrentActIndex + 1,
            Floor = state.ActFloor,
            Hp = player.Creature.CurrentHp,
            MaxHp = player.Creature.MaxHp,
            Gold = player.Gold,
            Relics = relics,
            Potions = potions,
        };

        // Attach screen-specific data
        if (screen == "card_reward")
        {
            response = response with { CardReward = BuildCardRewardInfo(player) };
        }
        else if (screen == "rewards")
        {
            response = response with { Rewards = BuildRewardsInfo(player) };
        }
        else if (screen is "event" or "ancient")
        {
            var eventInfo = BuildEventInfo(state);
            if (eventInfo is null || eventInfo.Options.Count == 0)
            {
                // Event is done but room hasn't transitioned — report as map
                screen = "map";
                response = response with { Screen = "map" };
            }
            else
            {
                response = response with { Event = eventInfo };
            }
        }
        else if (screen == "rest")
        {
            response = response with { RestSite = BuildRestSiteInfo(state) };
        }
        else if (screen == "treasure")
        {
            response = response with { Treasure = BuildTreasureInfo(player) };
        }
        else if (screen == "shop")
        {
            response = response with { Shop = BuildShopInfo(state) };
        }
        else if (screen == "card_select")
        {
            response = response with { CardSelect = BuildCardSelectInfo() };
        }
        else if (screen == "hand_select")
        {
            response = response with { HandSelect = BuildHandSelectInfo() };
        }

        return JsonSerializer.Serialize(response, JsonOptions);
    }

    private static string DetectScreen(MegaCrit.Sts2.Core.Runs.RunState state, NRun run)
    {
        // Check for pending in-combat card selection (e.g. Armaments, Acrobatics)
        if (AgentCardSelector.Pending is not null)
        {
            if (MegaCrit.Sts2.Core.Combat.CombatManager.Instance?.IsInProgress == true)
                return "hand_select";
            // Stale pending from ended combat — clean up
            AgentCardSelector.Cancel();
            AgentCardSelector.CleanupScope();
        }

        // Check overlay stack first — card reward selection is shown as an overlay
        var overlay = NOverlayStack.Instance?.Peek();
        if (overlay is NCardRewardSelectionScreen)
            return "card_reward";
        if (overlay is NCardGridSelectionScreen)
            return "card_select";
        if (overlay is NChooseABundleSelectionScreen)
            return "card_select";
        if (overlay is NChooseACardSelectionScreen)
            return "card_select";
        if (overlay is MegaCrit.Sts2.Core.Nodes.Screens.NRewardsScreen)
        {
            // If the map is open, the player has proceeded past rewards
            if (NMapScreen.Instance?.IsOpen == true)
                return "map";
            return "rewards";
        }

        // If CurrentRoom is still an EventRoom and the event still needs
        // interaction (unfinished or pre-finished), show the event screen —
        // even if the map is visually open — so the agent uses the event
        // tools (choose_event_option / proceed) instead of the map.
        if (state.CurrentRoom is EventRoom unfinishedEventRoom)
        {
            var em = unfinishedEventRoom.LocalMutableEvent;
            if (!em.IsFinished || unfinishedEventRoom.IsPreFinished)
                return DetectEventScreen(unfinishedEventRoom);
        }

        // A pending "proceed" event option button anywhere in the scene tree
        // blocks map navigation. Search the whole tree so we catch both the
        // EventRoom-path case and any lingering nodes elsewhere. This mirrors
        // the Proceed handler's effective behavior and prevents the agent from
        // thrashing the map while a hidden proceed button is still required.
        var sceneRoot = ((Godot.SceneTree)Godot.Engine.GetMainLoop()).Root;
        var allProceedButtons = ActionHandler.FindAll<NEventOptionButton>(sceneRoot)
            .Where(b => b.Option.IsProceed && !b.Option.IsLocked && b.Visible && b.IsVisibleInTree())
            .ToList();
        if (allProceedButtons.Count > 0)
        {
            bool wasAncient = state.CurrentRoom is EventRoom er
                && er.LocalMutableEvent is AncientEventModel;
            return wasAncient ? "ancient" : "event";
        }

        // Check if map is open (overrides room type — map can show over finished events etc.)
        if (NMapScreen.Instance?.IsOpen == true)
            return "map";

        // Fall back to room type
        var room = state.CurrentRoom;
        return room switch
        {
            EventRoom eventRoom => DetectEventScreen(eventRoom),
            CombatRoom => "combat",
            MapRoom => "map",
            RestSiteRoom => "rest",
            MerchantRoom => "shop",
            TreasureRoom => "treasure",
            _ => "unknown"
        };
    }

    private static string DetectEventScreen(EventRoom eventRoom)
    {
        var eventModel = eventRoom.LocalMutableEvent;
        bool isAncient = eventModel is AncientEventModel;

        // If the event is fully finished AND the map is open, we're done
        if (eventModel.IsFinished && NMapScreen.Instance?.IsOpen == true)
            return "map";

        // Options still showing — interact with the event normally
        if (eventModel.CurrentOptions.Count > 0)
            return isAncient ? "ancient" : "event";

        // Pre-finished / finished-but-map-closed — still in the event room
        // awaiting a proceed click to complete the transition.
        if (eventRoom.IsPreFinished || eventModel.IsFinished)
            return isAncient ? "ancient" : "event";

        return "waiting";
    }

    private static CardRewardInfo BuildCardRewardInfo(MegaCrit.Sts2.Core.Entities.Players.Player player)
    {
        // Find the active CardReward from the player's reward sets
        // The card reward screen is shown via overlay; find it from the overlay
        var overlay = NOverlayStack.Instance?.Peek();
        if (overlay is NCardRewardSelectionScreen cardScreen)
        {
            var cards = new List<CardInfo>();
            foreach (var option in cardScreen._options)
            {
                cards.Add(CombatHandler.BuildCardInfo(option.Card));
            }
            return new CardRewardInfo
            {
                Cards = cards,
                CanSkip = true
            };
        }
        return new CardRewardInfo();
    }

    private static RewardScreenInfo BuildRewardsInfo(MegaCrit.Sts2.Core.Entities.Players.Player player)
    {
        var overlay = NOverlayStack.Instance?.Peek();
        if (overlay is not NRewardsScreen rewardsScreen)
            return new RewardScreenInfo();

        var rewards = new List<RewardItemInfo>();
        foreach (var child in rewardsScreen._rewardButtons)
        {
            Reward? reward = null;
            if (child is NRewardButton button)
                reward = button.Reward;

            if (reward is null) continue;

            var type = reward switch
            {
                CardReward => "card",
                GoldReward => "gold",
                PotionReward => "potion",
                RelicReward => "relic",
                CardRemovalReward => "remove_card",
                SpecialCardReward => "special_card",
                _ => "unknown"
            };

            rewards.Add(new RewardItemInfo
            {
                Type = type,
                Description = reward.Description?.GetFormattedText() ?? ""
            });
        }

        return new RewardScreenInfo { Rewards = rewards };
    }

    private static EventInfo? BuildEventInfo(MegaCrit.Sts2.Core.Runs.RunState state)
    {
        if (state.CurrentRoom is not EventRoom eventRoom)
            return null;

        var eventModel = eventRoom.LocalMutableEvent;
        bool isAncient = eventModel is AncientEventModel;

        var options = new List<EventOptionInfo>();
        for (int i = 0; i < eventModel.CurrentOptions.Count; i++)
        {
            var option = eventModel.CurrentOptions[i];
            options.Add(new EventOptionInfo
            {
                Index = i,
                Label = CombatHandler.CleanDescription(option.Title?.GetFormattedText() ?? ""),
                Description = CombatHandler.CleanDescription(option.Description?.GetFormattedText() ?? ""),
                IsLocked = option.IsLocked,
                IsProceed = option.IsProceed
            });
        }

        return new EventInfo
        {
            Id = eventModel.Id.ToString(),
            Name = CombatHandler.CleanDescription(eventModel.Title?.GetFormattedText() ?? eventModel.Id.ToString()),
            IsAncient = isAncient,
            Body = GetEventBody(eventModel),
            Options = options
        };
    }

    private static RestSiteInfo? BuildRestSiteInfo(MegaCrit.Sts2.Core.Runs.RunState state)
    {
        if (state.CurrentRoom is not RestSiteRoom restRoom)
            return null;

        var options = new List<RestSiteOptionInfo>();
        foreach (var option in restRoom.Options)
        {
            options.Add(new RestSiteOptionInfo
            {
                Id = option.OptionId,
                Label = CombatHandler.CleanDescription(option.Title?.GetFormattedText() ?? option.OptionId),
                Description = CombatHandler.CleanDescription(option.Description?.GetFormattedText() ?? ""),
                IsEnabled = option.IsEnabled
            });
        }

        return new RestSiteInfo { Options = options };
    }

    private static TreasureInfo? BuildTreasureInfo(MegaCrit.Sts2.Core.Entities.Players.Player player)
    {
        // The treasure relic is the most recently added relic
        var lastRelic = player.Relics.LastOrDefault();
        if (lastRelic is null)
            return new TreasureInfo();

        return new TreasureInfo
        {
            RelicId = lastRelic.Id.ToString(),
            RelicName = lastRelic.Title?.GetFormattedText() ?? lastRelic.Id.ToString(),
            RelicDescription = CombatHandler.CleanDescription(lastRelic.DynamicDescription?.GetFormattedText() ?? "")
        };
    }

    private static CardSelectInfo? BuildCardSelectInfo()
    {
        var overlay = NOverlayStack.Instance?.Peek();

        // Card grid selection (upgrade, transform, remove, etc.)
        if (overlay is NCardGridSelectionScreen gridScreen)
        {
            string screenType = gridScreen switch
            {
                NDeckUpgradeSelectScreen => "upgrade",
                NDeckTransformSelectScreen => "transform",
                NDeckCardSelectScreen => "select",
                _ => gridScreen.GetType().Name
            };

            var cards = new List<CardInfo>();
            foreach (var card in gridScreen._cards)
            {
                cards.Add(CombatHandler.BuildCardInfo(card));
            }

            return new CardSelectInfo { ScreenType = screenType, Cards = cards };
        }

        // Bundle selection (e.g. Scroll Boxes — pick between card packs)
        if (overlay is NChooseABundleSelectionScreen bundleScreen)
        {
            var node = (Node)bundleScreen;
            var bundles = ActionHandler.FindAll<MegaCrit.Sts2.Core.Nodes.Cards.NCardBundle>(node);

            var cards = new List<CardInfo>();
            for (int i = 0; i < bundles.Count; i++)
            {
                // Represent each bundle as a "card" with its contents in the description
                var bundleCards = ActionHandler.FindAll<MegaCrit.Sts2.Core.Nodes.Cards.Holders.NGridCardHolder>(bundles[i]);
                var cardNames = string.Join(", ", bundleCards.Select(h => h.CardNode?.Model?.TitleLocString?.GetFormattedText() ?? "?"));
                cards.Add(new CardInfo
                {
                    Id = $"bundle_{i}",
                    Name = $"Pack {i + 1}",
                    Cost = 0,
                    Type = "bundle",
                    Description = cardNames,
                    Upgraded = false
                });
            }

            return new CardSelectInfo { ScreenType = "bundle", Cards = cards };
        }

        // Choose-a-card screen
        if (overlay is NChooseACardSelectionScreen chooseScreen)
        {
            var node = (Node)chooseScreen;
            var holders = ActionHandler.FindAll<MegaCrit.Sts2.Core.Nodes.Cards.Holders.NGridCardHolder>(node);

            var cards = new List<CardInfo>();
            foreach (var holder in holders)
            {
                if (holder.CardNode?.Model is { } card)
                    cards.Add(CombatHandler.BuildCardInfo(card));
            }

            return new CardSelectInfo { ScreenType = "choose", Cards = cards };
        }

        return null;
    }

    private static HandSelectInfo? BuildHandSelectInfo()
    {
        var pending = AgentCardSelector.Pending;
        if (pending is null) return null;

        var cards = new List<CardInfo>();
        foreach (var card in pending.Options)
            cards.Add(CombatHandler.BuildCardInfo(card));

        return new HandSelectInfo
        {
            TriggerCard = pending.TriggerCardName,
            TriggerDescription = pending.TriggerCardDescription,
            MinSelect = pending.MinSelect,
            MaxSelect = pending.MaxSelect,
            Cards = cards
        };
    }

    private static ShopInfo? BuildShopInfo(MegaCrit.Sts2.Core.Runs.RunState state)
    {
        if (state.CurrentRoom is not MerchantRoom merchantRoom)
            return null;

        var inventory = merchantRoom.Inventory;

        var cards = new List<ShopCardInfo>();
        foreach (var entry in inventory.CardEntries)
        {
            if (!entry.IsStocked || entry.CreationResult is null) continue;
            var card = entry.CreationResult.Card;
            var cardInfo = CombatHandler.BuildCardInfo(card);
            cards.Add(new ShopCardInfo
            {
                Id = cardInfo.Id,
                Name = cardInfo.Name,
                Cost = cardInfo.Cost,
                Type = cardInfo.Type,
                Description = cardInfo.Description,
                Upgraded = cardInfo.Upgraded,
                Price = entry.Cost
            });
        }

        var relics = new List<ShopRelicInfo>();
        foreach (var entry in inventory.RelicEntries)
        {
            if (!entry.IsStocked || entry.Model is null) continue;
            relics.Add(new ShopRelicInfo
            {
                Id = entry.Model.Id.ToString(),
                Name = entry.Model.Title?.GetFormattedText() ?? entry.Model.Id.ToString(),
                Description = CombatHandler.CleanDescription(entry.Model.DynamicDescription?.GetFormattedText() ?? ""),
                Price = entry.Cost
            });
        }

        var potions = new List<ShopPotionInfo>();
        foreach (var entry in inventory.PotionEntries)
        {
            if (!entry.IsStocked || entry.Model is null) continue;
            potions.Add(new ShopPotionInfo
            {
                Id = entry.Model.Id.ToString(),
                Name = entry.Model.Title?.GetFormattedText() ?? entry.Model.Id.ToString(),
                Price = entry.Cost
            });
        }

        int? removalCost = null;
        if (inventory.CardRemovalEntry is { IsStocked: true })
            removalCost = inventory.CardRemovalEntry.Cost;

        return new ShopInfo
        {
            Cards = cards,
            Relics = relics,
            Potions = potions,
            CardRemovalCost = removalCost
        };
    }

    private static string GetEventBody(EventModel eventModel)
    {
        // Try the current description first (set after event begins)
        var desc = eventModel.Description;
        if (desc is not null)
        {
            var text = desc.GetFormattedText();
            // If GetFormattedText returned the raw key (loc miss), treat as empty
            if (!text.Contains('.') || text.Contains(' '))
                return CombatHandler.CleanDescription(text);
        }

        // Fall back to initial description
        var initial = eventModel.InitialDescription;
        if (initial is not null)
        {
            var text = initial.GetFormattedText();
            if (!text.Contains('.') || text.Contains(' '))
                return CombatHandler.CleanDescription(text);
        }

        return "";
    }

    public static string GetDeck()
    {
        var run = NRun.Instance;
        if (run is null)
            return JsonSerializer.Serialize(new { error = "No active run" }, JsonOptions);

        var player = run._state.Players.FirstOrDefault();
        if (player is null)
            return JsonSerializer.Serialize(new { error = "No player found" }, JsonOptions);

        // Get deck cards — try combat piles first, fall back to deck pile
        var cards = new List<CardInfo>();
        var playerCombat = player.PlayerCombatState;
        if (playerCombat is not null && playerCombat.AllCards.Any())
        {
            // In combat: deck = all cards across all piles
            foreach (var card in playerCombat.AllCards)
                cards.Add(CombatHandler.BuildCardInfo(card));
        }
        else
        {
            // Outside combat (or combat state empty): deck pile
            foreach (var card in player.Deck.Cards)
                cards.Add(CombatHandler.BuildCardInfo(card));
        }

        cards.Sort((a, b) => string.Compare(a.Name, b.Name, StringComparison.Ordinal));

        return JsonSerializer.Serialize(new DeckResponse { Cards = cards }, JsonOptions);
    }

    public static string GetAvailableActions()
    {
        // TODO: Replace with real action enumeration
        var actions = new AvailableActionsResponse
        {
            WaitingForInput = true,
            Actions = []
        };
        return JsonSerializer.Serialize(actions, JsonOptions);
    }

    public static string GetHealth()
    {
        return JsonSerializer.Serialize(new HealthResponse(), JsonOptions);
    }
}

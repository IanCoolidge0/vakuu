using System.Text.Json;
using MegaCrit.Sts2.Core.Combat;
using MegaCrit.Sts2.Core.Commands;
using MegaCrit.Sts2.Core.Context;
using MegaCrit.Sts2.Core.Entities.Cards;
using MegaCrit.Sts2.Core.Entities.Creatures;
using MegaCrit.Sts2.Core.Entities.Players;
using MegaCrit.Sts2.Core.GameActions;
using MegaCrit.Sts2.Core.GameActions.Multiplayer;
using sts2_headless.sts2_headlessCode.Server;
using MegaCrit.Sts2.Core.Models;
using MegaCrit.Sts2.Core.Nodes;
using MegaCrit.Sts2.Core.Runs;
using sts2_headless.sts2_headlessCode.Models;

namespace sts2_headless.sts2_headlessCode.Server.Handlers;

public static class CombatActionHandler
{
    private static readonly JsonSerializerOptions JsonOptions = new() { WriteIndented = true };
    private const int MaxWaitMs = 30000;
    private const int PollIntervalMs = 50;

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

        // Validate we're in combat
        var run = NRun.Instance;
        if (run is null)
            return Error("No active run.");

        RunState state = run._state;
        Player? player = state.Players.FirstOrDefault();
        if (player is null)
            return Error("No player found.");

        var combatState = player.Creature.CombatState;
        var playerCombat = player.PlayerCombatState;
        if (combatState is null || playerCombat is null)
            return Error("Not in combat.");

        if (!CombatManager.Instance.IsInProgress)
            return Error("Combat is not in progress.");

        string result = request.Type switch
        {
            "play_card" => PlayCard(request, player, playerCombat, combatState),
            "end_turn" => EndTurn(player),
            "use_potion" => UsePotion(request, player, combatState),
            _ => Error($"Unknown combat action type: {request.Type}")
        };

        // If the action failed validation, return immediately
        var response = JsonSerializer.Deserialize<ActionResponse>(result);
        if (response is not { Success: true })
            return result;

        // Wait until the game is ready for the next input
        await WaitForReady();

        return result;
    }

    /// <summary>
    /// Waits until combat is back in play phase (ready for next action) or combat has ended.
    /// Uses Task.Delay to yield back to the game loop between checks.
    /// </summary>
    private static async Task WaitForReady()
    {
        // Small initial delay to let the action start processing
        await Task.Delay(10);

        int waited = 10;
        while (waited < MaxWaitMs)
        {
            // Combat ended — agent should poll /game/state to see rewards
            if (!CombatManager.Instance.IsInProgress)
                return;

            // Back in play phase — ready for next action
            if (CombatManager.Instance.IsPlayPhase)
                return;

            await Task.Delay(PollIntervalMs);
            waited += PollIntervalMs;
        }
        // Timeout — return anyway, let the agent figure out the state
    }

    private static string PlayCard(CombatActionRequest request, Player player,
        PlayerCombatState playerCombat, CombatState combatState)
    {
        if (!CombatManager.Instance.IsPlayPhase)
            return Error("Not in play phase.");

        if (request.CardIndex is null)
            return Error("play_card requires card_index.");

        int cardIndex = request.CardIndex.Value;
        var hand = playerCombat.Hand.Cards;

        if (cardIndex < 0 || cardIndex >= hand.Count)
            return Error($"card_index {cardIndex} out of range (hand has {hand.Count} cards).");

        CardModel card = hand[cardIndex];

        if (!card.CanPlay(out UnplayableReason reason, out AbstractModel? _))
            return Error($"Card '{card.Id}' cannot be played: {reason}");

        // Resolve target
        Creature? target = null;
        if (card.TargetType == TargetType.AnyEnemy)
        {
            if (request.TargetIndex is null)
                return Error($"Card '{card.Id}' requires a target (target_index).");

            var enemies = combatState.HittableEnemies;
            int targetIndex = request.TargetIndex.Value;

            if (targetIndex < 0 || targetIndex >= enemies.Count)
                return Error($"target_index {targetIndex} out of range ({enemies.Count} hittable enemies).");

            target = enemies[targetIndex];
        }

        IDisposable? selectorScope = null;
        if (request.SelectIndex is not null)
        {
            selectorScope = CardSelectCmd.PushSelector(new AgentCardSelector(request.SelectIndex.Value));
        }

        var action = new PlayCardAction(card, target);
        RunManager.Instance.ActionQueueSynchronizer.RequestEnqueue(action);

        // Clean up selector after a delay to let the action resolve
        if (selectorScope is not null)
        {
            Task.Delay(5000).ContinueWith(_ => selectorScope.Dispose());
        }

        return Success($"Played {card.Id}");
    }

    private static string EndTurn(Player player)
    {
        if (!CombatManager.Instance.IsPlayPhase)
            return Error("Not in play phase.");

        PlayerCmd.EndTurn(player, canBackOut: false);

        return Success("Ended turn.");
    }

    private static string UsePotion(CombatActionRequest request, Player player, CombatState combatState)
    {
        if (!CombatManager.Instance.IsPlayPhase)
            return Error("Not in play phase.");

        if (request.PotionIndex is null)
            return Error("use_potion requires potion_index.");

        int potionIndex = request.PotionIndex.Value;
        var potionSlots = player.PotionSlots;

        if (potionIndex < 0 || potionIndex >= potionSlots.Count)
            return Error($"potion_index {potionIndex} out of range ({potionSlots.Count} slots).");

        var potion = potionSlots[potionIndex];
        if (potion is null)
            return Error($"Potion slot {potionIndex} is empty.");

        // Resolve target
        Creature? target = null;
        if (potion.TargetType == TargetType.AnyEnemy)
        {
            if (request.TargetIndex is null)
                return Error($"Potion '{potion.Id}' requires a target (target_index).");

            var enemies = combatState.HittableEnemies;
            int targetIndex = request.TargetIndex.Value;

            if (targetIndex < 0 || targetIndex >= enemies.Count)
                return Error($"target_index {targetIndex} out of range ({enemies.Count} hittable enemies).");

            target = enemies[targetIndex];
        }
        else if (potion.TargetType is TargetType.Self or TargetType.AnyAlly or TargetType.AnyPlayer)
        {
            target = player.Creature;
        }

        potion.EnqueueManualUse(target);

        return Success($"Used potion {potion.Id}");
    }

    private static string Success(string message)
    {
        return JsonSerializer.Serialize(new ActionResponse
        {
            Success = true,
            Message = message
        }, JsonOptions);
    }

    private static string Error(string error)
    {
        return JsonSerializer.Serialize(new ActionResponse
        {
            Success = false,
            Error = error
        }, JsonOptions);
    }
}

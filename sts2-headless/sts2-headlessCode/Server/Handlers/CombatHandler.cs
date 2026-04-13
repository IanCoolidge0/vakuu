using System.Text.Json;
using System.Text.RegularExpressions;
using MegaCrit.Sts2.Core.Combat;
using MegaCrit.Sts2.Core.Entities.Cards;
using MegaCrit.Sts2.Core.Entities.Creatures;
using MegaCrit.Sts2.Core.Entities.Players;
using MegaCrit.Sts2.Core.Models;
using MegaCrit.Sts2.Core.MonsterMoves.Intents;
using MegaCrit.Sts2.Core.Nodes;
using sts2_headless.sts2_headlessCode.Models;

namespace sts2_headless.sts2_headlessCode.Server.Handlers;

public static class CombatHandler
{
    private static readonly JsonSerializerOptions JsonOptions = new() { WriteIndented = true };
    private static readonly Regex BbCodeRegex = new(@"\[/?[^\]]+\]", RegexOptions.Compiled);
    private static readonly Regex UnresolvedVarRegex = new(@"\{[^}]+\}", RegexOptions.Compiled);

    public static string GetCombatState()
    {
        var run = NRun.Instance;
        if (run is null)
            return JsonSerializer.Serialize(new { error = "No active run" }, JsonOptions);

        var state = run._state;
        var player = state.Players.FirstOrDefault();
        if (player is null)
            return JsonSerializer.Serialize(new { error = "No player found" }, JsonOptions);

        var combatState = player.Creature.CombatState;
        var playerCombat = player.PlayerCombatState;
        if (combatState is null || playerCombat is null)
            return JsonSerializer.Serialize(new { error = "Not in combat" }, JsonOptions);

        var enemies = new List<EnemyInfo>();
        for (int i = 0; i < combatState.Enemies.Count; i++)
        {
            var enemy = combatState.Enemies[i];
            enemies.Add(BuildEnemyInfo(i, enemy, combatState));
        }

        var hand = new List<CardInfo>();
        foreach (var card in playerCombat.Hand.Cards)
        {
            hand.Add(BuildCardInfo(card));
        }

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

        var response = new CombatStateResponse
        {
            Turn = combatState.RoundNumber,
            Energy = playerCombat.Energy,
            MaxEnergy = playerCombat.MaxEnergy,
            Player = new CombatPlayerInfo
            {
                Name = player.Creature.Name,
                Hp = player.Creature.CurrentHp,
                MaxHp = player.Creature.MaxHp,
                Block = player.Creature.Block,
                Powers = BuildPowerList(player.Creature)
            },
            Enemies = enemies,
            Hand = hand,
            Potions = potions,
            Relics = player.Relics.Select(r => new RelicInfo
            {
                Id = r.Id.ToString(),
                Name = r.Title?.GetFormattedText() ?? r.Id.ToString(),
                Counter = r.ShowCounter ? r.DisplayAmount : null
            }).ToList(),
            DrawPileCount = playerCombat.DrawPile.Cards.Count,
            DiscardPileCount = playerCombat.DiscardPile.Cards.Count,
            ExhaustPileCount = playerCombat.ExhaustPile.Cards.Count
        };

        return JsonSerializer.Serialize(response, JsonOptions);
    }

    public static string GetPiles()
    {
        var run = NRun.Instance;
        if (run is null)
            return JsonSerializer.Serialize(new { error = "No active run" }, JsonOptions);

        var player = run._state.Players.FirstOrDefault();
        var playerCombat = player?.PlayerCombatState;
        if (playerCombat is null)
            return JsonSerializer.Serialize(new { error = "Not in combat" }, JsonOptions);

        // Draw pile: show contents but shuffled (player can see contents but not order)
        var drawPile = playerCombat.DrawPile.Cards.Select(BuildCardInfo).ToList();
        drawPile.Sort((a, b) => string.Compare(a.Name, b.Name, StringComparison.Ordinal));

        var response = new PilesResponse
        {
            DrawPileCount = playerCombat.DrawPile.Cards.Count,
            DrawPile = drawPile,
            DiscardPile = playerCombat.DiscardPile.Cards.Select(BuildCardInfo).ToList(),
            ExhaustPile = playerCombat.ExhaustPile.Cards.Select(BuildCardInfo).ToList()
        };

        return JsonSerializer.Serialize(response, JsonOptions);
    }

    private static EnemyInfo BuildEnemyInfo(int index, Creature enemy, CombatState combatState)
    {
        var intents = new List<IntentInfo>();
        if (enemy.Monster?.NextMove.Intents is { } moveIntents)
        {
            foreach (var intent in moveIntents)
            {
                var intentInfo = new IntentInfo
                {
                    Type = intent.IntentType.ToString().ToLower()
                };

                if (intent is AttackIntent attackIntent)
                {
                    var targets = combatState.Allies;
                    intentInfo = intentInfo with
                    {
                        Damage = attackIntent.GetSingleDamage(targets, enemy),
                        Hits = attackIntent.Repeats
                    };
                }

                intents.Add(intentInfo);
            }
        }

        return new EnemyInfo
        {
            Index = index,
            Id = enemy.Monster?.Id.ToString() ?? "",
            Name = enemy.Name,
            Hp = enemy.CurrentHp,
            MaxHp = enemy.MaxHp,
            Block = enemy.Block,
            Powers = BuildPowerList(enemy),
            Intents = intents,
            IsDead = enemy.IsDead
        };
    }

    internal static CardInfo BuildCardInfo(CardModel card)
    {
        int cost;
        if (card.EnergyCost.CostsX)
            cost = -1;
        else
            cost = card.EnergyCost.GetWithModifiers(CostModifiers.All);

        var description = card.Description;
        card.DynamicVars.AddTo(description);

        return new CardInfo
        {
            Id = card.Id.ToString(),
            Name = card.TitleLocString?.GetFormattedText() ?? card.Id.ToString(),
            Cost = cost,
            Type = card.Type.ToString().ToLower(),
            Description = CleanDescription(description?.GetFormattedText() ?? ""),
            Upgraded = card.IsUpgraded
        };
    }

    private static List<PowerInfo> BuildPowerList(Creature creature)
    {
        var powers = new List<PowerInfo>();
        foreach (var power in creature.Powers)
        {
            powers.Add(new PowerInfo
            {
                Id = power.Id.ToString(),
                Name = power.Title?.GetFormattedText() ?? power.Id.ToString(),
                Amount = power.DisplayAmount
            });
        }
        return powers;
    }

    internal static string CleanDescription(string text)
    {
        text = BbCodeRegex.Replace(text, "");
        text = UnresolvedVarRegex.Replace(text, "");
        // Clean up leftover whitespace artifacts
        text = text.Replace("\n\n", "\n").Trim();
        return text;
    }
}

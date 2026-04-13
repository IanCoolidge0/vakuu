using System.Text.Json.Serialization;

namespace sts2_headless.sts2_headlessCode.Models;

public record GameStateResponse
{
    [JsonPropertyName("screen")] public string Screen { get; init; } = "";
    [JsonPropertyName("character")] public string Character { get; init; } = "";
    [JsonPropertyName("ascension")] public int Ascension { get; init; }
    [JsonPropertyName("act")] public int Act { get; init; }
    [JsonPropertyName("floor")] public int Floor { get; init; }
    [JsonPropertyName("hp")] public int Hp { get; init; }
    [JsonPropertyName("max_hp")] public int MaxHp { get; init; }
    [JsonPropertyName("gold")] public int Gold { get; init; }
    [JsonPropertyName("relics")] public List<RelicInfo> Relics { get; init; } = [];
    [JsonPropertyName("potions")] public List<PotionSlotInfo> Potions { get; init; } = [];

    // Screen-specific data (only one of these is populated based on screen type)
    [JsonPropertyName("card_reward")]
    [JsonIgnore(Condition = JsonIgnoreCondition.WhenWritingNull)]
    public CardRewardInfo? CardReward { get; init; }

    [JsonPropertyName("rewards")]
    [JsonIgnore(Condition = JsonIgnoreCondition.WhenWritingNull)]
    public RewardScreenInfo? Rewards { get; init; }

    [JsonPropertyName("event")]
    [JsonIgnore(Condition = JsonIgnoreCondition.WhenWritingNull)]
    public EventInfo? Event { get; init; }

    [JsonPropertyName("rest_site")]
    [JsonIgnore(Condition = JsonIgnoreCondition.WhenWritingNull)]
    public RestSiteInfo? RestSite { get; init; }

    [JsonPropertyName("treasure")]
    [JsonIgnore(Condition = JsonIgnoreCondition.WhenWritingNull)]
    public TreasureInfo? Treasure { get; init; }

    [JsonPropertyName("shop")]
    [JsonIgnore(Condition = JsonIgnoreCondition.WhenWritingNull)]
    public ShopInfo? Shop { get; init; }

    [JsonPropertyName("card_select")]
    [JsonIgnore(Condition = JsonIgnoreCondition.WhenWritingNull)]
    public CardSelectInfo? CardSelect { get; init; }
}

public record CardSelectInfo
{
    [JsonPropertyName("screen_type")] public string ScreenType { get; init; } = "";
    [JsonPropertyName("cards")] public List<CardInfo> Cards { get; init; } = [];
}

public record ShopInfo
{
    [JsonPropertyName("cards")] public List<ShopCardInfo> Cards { get; init; } = [];
    [JsonPropertyName("relics")] public List<ShopRelicInfo> Relics { get; init; } = [];
    [JsonPropertyName("potions")] public List<ShopPotionInfo> Potions { get; init; } = [];
    [JsonPropertyName("card_removal_cost")] public int? CardRemovalCost { get; init; }
}

public record ShopCardInfo
{
    [JsonPropertyName("id")] public string Id { get; init; } = "";
    [JsonPropertyName("name")] public string Name { get; init; } = "";
    [JsonPropertyName("cost")] public int Cost { get; init; }
    [JsonPropertyName("type")] public string Type { get; init; } = "";
    [JsonPropertyName("description")] public string Description { get; init; } = "";
    [JsonPropertyName("upgraded")] public bool Upgraded { get; init; }
    [JsonPropertyName("price")] public int Price { get; init; }
}

public record ShopRelicInfo
{
    [JsonPropertyName("id")] public string Id { get; init; } = "";
    [JsonPropertyName("name")] public string Name { get; init; } = "";
    [JsonPropertyName("description")] public string Description { get; init; } = "";
    [JsonPropertyName("price")] public int Price { get; init; }
}

public record ShopPotionInfo
{
    [JsonPropertyName("id")] public string Id { get; init; } = "";
    [JsonPropertyName("name")] public string Name { get; init; } = "";
    [JsonPropertyName("price")] public int Price { get; init; }
}

public record RestSiteInfo
{
    [JsonPropertyName("options")] public List<RestSiteOptionInfo> Options { get; init; } = [];
}

public record RestSiteOptionInfo
{
    [JsonPropertyName("id")] public string Id { get; init; } = "";
    [JsonPropertyName("label")] public string Label { get; init; } = "";
    [JsonPropertyName("description")] public string Description { get; init; } = "";
    [JsonPropertyName("is_enabled")] public bool IsEnabled { get; init; }
}

public record TreasureInfo
{
    [JsonPropertyName("relic_id")] public string RelicId { get; init; } = "";
    [JsonPropertyName("relic_name")] public string RelicName { get; init; } = "";
    [JsonPropertyName("relic_description")] public string RelicDescription { get; init; } = "";
}

public record EventInfo
{
    [JsonPropertyName("id")] public string Id { get; init; } = "";
    [JsonPropertyName("name")] public string Name { get; init; } = "";
    [JsonPropertyName("is_ancient")] public bool IsAncient { get; init; }
    [JsonPropertyName("body")] public string Body { get; init; } = "";
    [JsonPropertyName("options")] public List<EventOptionInfo> Options { get; init; } = [];
}

public record EventOptionInfo
{
    [JsonPropertyName("index")] public int Index { get; init; }
    [JsonPropertyName("label")] public string Label { get; init; } = "";
    [JsonPropertyName("description")] public string Description { get; init; } = "";
    [JsonPropertyName("is_locked")] public bool IsLocked { get; init; }
    [JsonPropertyName("is_proceed")] public bool IsProceed { get; init; }
}

public record CardRewardInfo
{
    [JsonPropertyName("cards")] public List<CardInfo> Cards { get; init; } = [];
    [JsonPropertyName("can_skip")] public bool CanSkip { get; init; }
}

public record RewardScreenInfo
{
    [JsonPropertyName("rewards")] public List<RewardItemInfo> Rewards { get; init; } = [];
}

public record RewardItemInfo
{
    [JsonPropertyName("type")] public string Type { get; init; } = "";
    [JsonPropertyName("description")] public string Description { get; init; } = "";
}

public record CombatStateResponse
{
    [JsonPropertyName("turn")] public int Turn { get; init; }
    [JsonPropertyName("energy")] public int Energy { get; init; }
    [JsonPropertyName("max_energy")] public int MaxEnergy { get; init; }
    [JsonPropertyName("player")] public CombatPlayerInfo Player { get; init; } = new();
    [JsonPropertyName("enemies")] public List<EnemyInfo> Enemies { get; init; } = [];
    [JsonPropertyName("hand")] public List<CardInfo> Hand { get; init; } = [];
    [JsonPropertyName("potions")] public List<PotionSlotInfo> Potions { get; init; } = [];
    [JsonPropertyName("relics")] public List<RelicInfo> Relics { get; init; } = [];
    [JsonPropertyName("draw_pile_count")] public int DrawPileCount { get; init; }
    [JsonPropertyName("discard_pile_count")] public int DiscardPileCount { get; init; }
    [JsonPropertyName("exhaust_pile_count")] public int ExhaustPileCount { get; init; }
}

public record CombatPlayerInfo
{
    [JsonPropertyName("name")] public string Name { get; init; } = "";
    [JsonPropertyName("hp")] public int Hp { get; init; }
    [JsonPropertyName("max_hp")] public int MaxHp { get; init; }
    [JsonPropertyName("block")] public int Block { get; init; }
    [JsonPropertyName("powers")] public List<PowerInfo> Powers { get; init; } = [];
}

public record EnemyInfo
{
    [JsonPropertyName("index")] public int Index { get; init; }
    [JsonPropertyName("id")] public string Id { get; init; } = "";
    [JsonPropertyName("name")] public string Name { get; init; } = "";
    [JsonPropertyName("hp")] public int Hp { get; init; }
    [JsonPropertyName("max_hp")] public int MaxHp { get; init; }
    [JsonPropertyName("block")] public int Block { get; init; }
    [JsonPropertyName("powers")] public List<PowerInfo> Powers { get; init; } = [];
    [JsonPropertyName("intents")] public List<IntentInfo> Intents { get; init; } = [];
    [JsonPropertyName("is_dead")] public bool IsDead { get; init; }
}

public record IntentInfo
{
    [JsonPropertyName("type")] public string Type { get; init; } = "";
    [JsonPropertyName("damage")] public int? Damage { get; init; }
    [JsonPropertyName("hits")] public int? Hits { get; init; }
}

public record PotionSlotInfo
{
    [JsonPropertyName("index")] public int Index { get; init; }
    [JsonPropertyName("id")] public string? Id { get; init; }
    [JsonPropertyName("name")] public string? Name { get; init; }
}

public record PilesResponse
{
    [JsonPropertyName("draw_pile_count")] public int DrawPileCount { get; init; }
    [JsonPropertyName("draw_pile")] public List<CardInfo> DrawPile { get; init; } = [];
    [JsonPropertyName("discard_pile")] public List<CardInfo> DiscardPile { get; init; } = [];
    [JsonPropertyName("exhaust_pile")] public List<CardInfo> ExhaustPile { get; init; } = [];
}

public record CardInfo
{
    [JsonPropertyName("id")] public string Id { get; init; } = "";
    [JsonPropertyName("name")] public string Name { get; init; } = "";
    [JsonPropertyName("cost")] public int Cost { get; init; }
    [JsonPropertyName("type")] public string Type { get; init; } = "";
    [JsonPropertyName("description")] public string Description { get; init; } = "";
    [JsonPropertyName("upgraded")] public bool Upgraded { get; init; }
}

public record PowerInfo
{
    [JsonPropertyName("id")] public string Id { get; init; } = "";
    [JsonPropertyName("name")] public string Name { get; init; } = "";
    [JsonPropertyName("amount")] public int Amount { get; init; }
}

public record RelicInfo
{
    [JsonPropertyName("id")] public string Id { get; init; } = "";
    [JsonPropertyName("name")] public string Name { get; init; } = "";
    [JsonPropertyName("description")] public string Description { get; init; } = "";
    [JsonPropertyName("counter")]
    [JsonIgnore(Condition = JsonIgnoreCondition.WhenWritingNull)]
    public int? Counter { get; init; }
}

public record PotionInfo
{
    [JsonPropertyName("id")] public string Id { get; init; } = "";
    [JsonPropertyName("name")] public string Name { get; init; } = "";
    [JsonPropertyName("description")] public string Description { get; init; } = "";
}

public record MapResponse
{
    [JsonPropertyName("act")] public int Act { get; init; }
    [JsonPropertyName("act_name")] public string ActName { get; init; } = "";
    [JsonPropertyName("current_floor")] public int CurrentFloor { get; init; }
    [JsonPropertyName("current_node")] public string? CurrentNode { get; init; }
    [JsonPropertyName("visited_nodes")] public List<string> VisitedNodes { get; init; } = [];
    [JsonPropertyName("boss")] public string Boss { get; init; } = "";
    [JsonPropertyName("nodes")] public List<MapNodeInfo> Nodes { get; init; } = [];
}

public record MapNodeInfo
{
    [JsonPropertyName("id")] public string Id { get; init; } = "";
    [JsonPropertyName("type")] public string Type { get; init; } = "";
    [JsonPropertyName("col")] public int Col { get; init; }
    [JsonPropertyName("row")] public int Row { get; init; }
    [JsonPropertyName("children")] public List<string> Children { get; init; } = [];
    [JsonPropertyName("parents")] public List<string> Parents { get; init; } = [];
}

public record AvailableActionsResponse
{
    [JsonPropertyName("actions")] public List<ActionInfo> Actions { get; init; } = [];
    [JsonPropertyName("waiting_for_input")] public bool WaitingForInput { get; init; }
}

public record ActionInfo
{
    [JsonPropertyName("id")] public string Id { get; init; } = "";
    [JsonPropertyName("type")] public string Type { get; init; } = "";
    [JsonPropertyName("description")] public string Description { get; init; } = "";
    [JsonPropertyName("params")] public Dictionary<string, object>? Params { get; init; }
}

public record DeckResponse
{
    [JsonPropertyName("cards")] public List<CardInfo> Cards { get; init; } = [];
}

public record HealthResponse
{
    [JsonPropertyName("status")] public string Status { get; init; } = "ok";
}

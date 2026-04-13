using System.Text.Json.Serialization;

namespace sts2_headless.sts2_headlessCode.Models;

public record ActionResponse
{
    [JsonPropertyName("success")] public bool Success { get; init; }
    [JsonPropertyName("error")] public string? Error { get; init; }
    [JsonPropertyName("message")] public string? Message { get; init; }
}

public record CombatActionRequest
{
    [JsonPropertyName("type")] public string Type { get; init; } = "";
    [JsonPropertyName("card_index")] public int? CardIndex { get; init; }
    [JsonPropertyName("target_index")] public int? TargetIndex { get; init; }
    [JsonPropertyName("potion_index")] public int? PotionIndex { get; init; }
    [JsonPropertyName("select_index")] public int? SelectIndex { get; init; }
    [JsonPropertyName("col")] public int? Col { get; init; }
    [JsonPropertyName("row")] public int? Row { get; init; }
}

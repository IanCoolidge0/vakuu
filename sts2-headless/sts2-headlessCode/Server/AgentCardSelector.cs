using MegaCrit.Sts2.Core.Entities.CardRewardAlternatives;
using MegaCrit.Sts2.Core.Entities.Cards;
using MegaCrit.Sts2.Core.Models;
using MegaCrit.Sts2.Core.TestSupport;

namespace sts2_headless.sts2_headlessCode.Server;

/// <summary>
/// Card selector for agent-driven card selection during combat.
/// When the game asks for a card selection (e.g. Armaments upgrade, Acrobatics discard),
/// this selector blocks until the agent responds via the select_hand_card API.
/// </summary>
public class AgentCardSelector : ICardSelector
{
    private readonly string _triggerCardName;
    private readonly string _triggerCardDescription;

    private static PendingCardSelection? _pending;
    private static IDisposable? _selectorScope;

    public AgentCardSelector(string triggerCardName, string triggerCardDescription)
    {
        _triggerCardName = triggerCardName;
        _triggerCardDescription = triggerCardDescription;
    }

    /// <summary>The currently pending card selection, or null if none.</summary>
    public static PendingCardSelection? Pending => _pending;

    public Task<IEnumerable<CardModel>> GetSelectedCards(
        IEnumerable<CardModel> options, int minSelect, int maxSelect)
    {
        var pending = new PendingCardSelection(
            options.ToList(), minSelect, maxSelect,
            _triggerCardName, _triggerCardDescription);
        _pending = pending;
        return pending.WaitForResponseAsync();
    }

    /// <summary>Resolve the pending selection with the given card indices.</summary>
    public static void Respond(int[] selectedIndices)
    {
        var pending = _pending;
        if (pending is null) return;
        _pending = null;
        pending.SetResponse(selectedIndices);
    }

    /// <summary>Cancel any pending selection (e.g. on timeout or cleanup).</summary>
    public static void Cancel()
    {
        var pending = _pending;
        if (pending is null) return;
        _pending = null;
        pending.SetResponse(Array.Empty<int>());
    }

    public static void SetSelectorScope(IDisposable scope)
    {
        _selectorScope?.Dispose();
        _selectorScope = scope;
    }

    public static void CleanupScope()
    {
        _selectorScope?.Dispose();
        _selectorScope = null;
        _pending = null;
    }

    public CardModel? GetSelectedCardReward(
        IReadOnlyList<CardCreationResult> options,
        IReadOnlyList<CardRewardAlternative> alternatives)
    {
        // Not used for combat card selection
        return null;
    }
}

/// <summary>
/// Represents a card selection that the game is waiting for the agent to resolve.
/// </summary>
public class PendingCardSelection
{
    public IReadOnlyList<CardModel> Options { get; }
    public int MinSelect { get; }
    public int MaxSelect { get; }
    public string TriggerCardName { get; }
    public string TriggerCardDescription { get; }

    private readonly TaskCompletionSource<IEnumerable<CardModel>> _tcs = new();

    public PendingCardSelection(
        List<CardModel> options, int minSelect, int maxSelect,
        string triggerCardName, string triggerCardDescription)
    {
        Options = options;
        MinSelect = minSelect;
        MaxSelect = maxSelect;
        TriggerCardName = triggerCardName;
        TriggerCardDescription = triggerCardDescription;
    }

    public async Task<IEnumerable<CardModel>> WaitForResponseAsync()
    {
        return await _tcs.Task;
    }

    public void SetResponse(int[] indices)
    {
        var selected = indices
            .Where(i => i >= 0 && i < Options.Count)
            .Select(i => Options[i])
            .ToList();
        _tcs.TrySetResult(selected);
    }
}

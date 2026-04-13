using MegaCrit.Sts2.Core.Entities.CardRewardAlternatives;
using MegaCrit.Sts2.Core.Entities.Cards;
using MegaCrit.Sts2.Core.Models;
using MegaCrit.Sts2.Core.TestSupport;

namespace sts2_headless.sts2_headlessCode.Server;

/// <summary>
/// Card selector that picks by a pre-specified index. Used when the agent
/// plays a card that triggers a card selection prompt (e.g., Armaments).
/// </summary>
public class AgentCardSelector : ICardSelector
{
    private readonly int _selectIndex;

    public AgentCardSelector(int selectIndex)
    {
        _selectIndex = selectIndex;
    }

    public Task<IEnumerable<CardModel>> GetSelectedCards(IEnumerable<CardModel> options, int minSelect, int maxSelect)
    {
        var list = options.ToList();
        if (list.Count == 0 || _selectIndex < 0 || _selectIndex >= list.Count)
            return Task.FromResult<IEnumerable<CardModel>>(Array.Empty<CardModel>());

        return Task.FromResult<IEnumerable<CardModel>>(new[] { list[_selectIndex] });
    }

    public CardModel? GetSelectedCardReward(IReadOnlyList<CardCreationResult> options, IReadOnlyList<CardRewardAlternative> alternatives)
    {
        if (options.Count == 0 || _selectIndex < 0 || _selectIndex >= options.Count)
            return null;

        return options[_selectIndex].Card;
    }
}

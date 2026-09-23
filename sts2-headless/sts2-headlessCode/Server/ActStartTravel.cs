using Godot;
using MegaCrit.Sts2.Core.Nodes;
using MegaCrit.Sts2.Core.Nodes.Screens.Map;
using MegaCrit.Sts2.Core.Rooms;

namespace sts2_headless.sts2_headlessCode.Server;

/// <summary>
/// Travels to the act's starting (ancient) node on its own.
///
/// Act 1 enters Neow automatically, but acts 2 and 3 start in a bare
/// MapRoom: the map opens with only the ancient node travelable and waits
/// for a click. With no current map coordinate the API reports that screen
/// as "waiting", so agents never get to click it and the run stalls until
/// someone clicks by hand. There is exactly one node to pick, so pick it.
/// </summary>
public static class ActStartTravel
{
    // Let the act banner and start-of-act map scroll begin before clicking.
    private const double SettleSeconds = 0.5;

    // The vote goes through the action queue, so the map stays travel-ready
    // for a few frames after voting. Re-voting then is harmless (once travel
    // starts, MapSelectionSynchronizer rejects votes from the old location)
    // but logs a warning each time, so wait before retrying a lost vote.
    private const double RetrySeconds = 3.0;

    private static double _readyFor;
    private static double _sinceClick = RetrySeconds;
    private static bool _loggedFailure;

    public static void Tick(double delta)
    {
        // Runs every frame from _Process: never let a failure escape and
        // repeat 60 times a second.
        try
        {
            TickInternal(delta);
        }
        catch (Exception ex)
        {
            if (!_loggedFailure)
                MainFile.Logger.Error($"Act-start auto-travel failed: {ex}");
            _loggedFailure = true;
        }
    }

    private static void TickInternal(double delta)
    {
        _sinceClick += delta;

        if (!TryGetActStartNode(out var mapScreen, out var start))
        {
            _readyFor = 0;
            return;
        }

        _readyFor += delta;
        if (_readyFor < SettleSeconds || _sinceClick < RetrySeconds)
            return;

        MainFile.Logger.Info($"Act start: traveling to the starting node {start.Point.coord}.");
        _sinceClick = 0;
        mapScreen.OnMapPointSelectedLocally(start);
    }

    private static bool TryGetActStartNode(out NMapScreen mapScreen, out NMapPoint start)
    {
        mapScreen = null!;
        start = null!;

        // Check the run first: outside a run the static map screen can point
        // at a freed node.
        var state = NRun.Instance?._state;
        if (state is null || state.CurrentRoom is not MapRoom || state.VisitedMapCoords.Count > 0)
            return false;

        var screen = NMapScreen.Instance;
        if (screen is null || !GodotObject.IsInstanceValid(screen)
            || !screen.IsOpen || !screen.IsTravelEnabled || screen.IsTraveling)
            return false;

        var node = screen._startingPointNode;
        if (node is null || !GodotObject.IsInstanceValid(node) || !node.IsTravelable)
            return false;

        mapScreen = screen;
        start = node;
        return true;
    }
}

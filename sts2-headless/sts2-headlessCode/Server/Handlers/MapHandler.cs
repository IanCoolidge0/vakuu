using System.Text.Json;
using MegaCrit.Sts2.Core.Map;
using MegaCrit.Sts2.Core.Nodes;
using MegaCrit.Sts2.Core.Runs;
using sts2_headless.sts2_headlessCode.Models;

namespace sts2_headless.sts2_headlessCode.Server.Handlers;

public static class MapHandler
{
    private static readonly JsonSerializerOptions JsonOptions = new() { WriteIndented = true };

    public static string GetMap()
    {
        var run = NRun.Instance;
        if (run is null)
        {
            return JsonSerializer.Serialize(new { error = "No active run" }, JsonOptions);
        }

        RunState state = run._state;
        ActMap map = state.Map;

        var currentCoord = state.CurrentMapCoord;
        string? currentNode = currentCoord.HasValue
            ? FormatNodeId(currentCoord.Value.col, currentCoord.Value.row)
            : null;

        var visitedNodes = new List<string>();
        foreach (var coord in state.VisitedMapCoords)
        {
            visitedNodes.Add(FormatNodeId(coord.col, coord.row));
        }

        var bossPoint = map.BossMapPoint;
        string bossName = state.Act.BossEncounter?.Id.ToString() ?? "unknown";

        // Collect all special + grid points, deduplicating by coordinate
        var seen = new HashSet<string>();
        var allPoints = new List<MapPoint>();

        // Add the starting/ancient point
        var startPoint = map.StartingMapPoint;
        if (startPoint is not null && seen.Add(FormatNodeId(startPoint.coord.col, startPoint.coord.row)))
        {
            allPoints.Add(startPoint);
        }

        // Add all grid points
        foreach (var point in map.GetAllMapPoints())
        {
            if (seen.Add(FormatNodeId(point.coord.col, point.coord.row)))
            {
                allPoints.Add(point);
            }
        }

        // Add boss point(s)
        if (seen.Add(FormatNodeId(bossPoint.coord.col, bossPoint.coord.row)))
        {
            allPoints.Add(bossPoint);
        }
        var secondBoss = map.SecondBossMapPoint;
        if (secondBoss is not null && seen.Add(FormatNodeId(secondBoss.coord.col, secondBoss.coord.row)))
        {
            allPoints.Add(secondBoss);
        }

        var nodes = new List<MapNodeInfo>();
        foreach (var point in allPoints)
        {
            var children = new List<string>();
            foreach (var child in point.Children)
            {
                children.Add(FormatNodeId(child.coord.col, child.coord.row));
            }

            var parents = new List<string>();
            foreach (var parent in point.parents)
            {
                parents.Add(FormatNodeId(parent.coord.col, parent.coord.row));
            }

            nodes.Add(new MapNodeInfo
            {
                Id = FormatNodeId(point.coord.col, point.coord.row),
                Type = MapPointTypeToString(point.PointType),
                Col = point.coord.col,
                Row = point.coord.row,
                Children = children,
                Parents = parents
            });
        }

        nodes.Sort((a, b) => a.Row != b.Row ? a.Row.CompareTo(b.Row) : a.Col.CompareTo(b.Col));

        var response = new MapResponse
        {
            Act = state.CurrentActIndex + 1,
            ActName = state.Act.Id.ToString(),
            CurrentFloor = state.ActFloor,
            CurrentNode = currentNode,
            VisitedNodes = visitedNodes,
            Boss = bossName,
            Nodes = nodes
        };

        return JsonSerializer.Serialize(response, JsonOptions);
    }

    private static string FormatNodeId(int col, int row)
    {
        return $"{col}_{row}";
    }

    private static string MapPointTypeToString(MapPointType type)
    {
        return type switch
        {
            MapPointType.Monster => "enemy",
            MapPointType.Elite => "elite",
            MapPointType.RestSite => "rest",
            MapPointType.Shop => "shop",
            MapPointType.Treasure => "treasure",
            MapPointType.Boss => "boss",
            MapPointType.Ancient => "ancient",
            MapPointType.Unknown => "unknown",
            MapPointType.Unassigned => "unassigned",
            _ => type.ToString().ToLower()
        };
    }
}

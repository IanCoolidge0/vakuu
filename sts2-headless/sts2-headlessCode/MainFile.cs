using Godot;
using HarmonyLib;
using MegaCrit.Sts2.Core.Modding;
using sts2_headless.sts2_headlessCode.Server;

namespace sts2_headless.sts2_headlessCode;

[ModInitializer(nameof(Initialize))]
public partial class MainFile : Node
{
    public const string ModId = "sts2_headless";

    public static MegaCrit.Sts2.Core.Logging.Logger Logger { get; } = new(ModId, MegaCrit.Sts2.Core.Logging.LogType.Generic);

    public static void Initialize()
    {
        Harmony harmony = new(ModId);
        harmony.PatchAll();

        var instance = new MainFile();
        instance.Name = ModId;
        ((SceneTree)Engine.GetMainLoop()).Root.CallDeferred(Node.MethodName.AddChild, instance);

        ApiServer.Instance.Start();
    }

    public override void _Process(double delta)
    {
        RequestDispatcher.Instance.ProcessPendingRequests();
    }

    public override void _ExitTree()
    {
        ApiServer.Instance.Stop();
    }
}

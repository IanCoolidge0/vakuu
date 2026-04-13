using System.Net;
using System.Text;
using sts2_headless.sts2_headlessCode.Server.Handlers;

namespace sts2_headless.sts2_headlessCode.Server;

public class ApiServer
{
    public static ApiServer Instance { get; } = new();

    private const string Prefix = "http://localhost:58232/";
    private HttpListener? _listener;
    private CancellationTokenSource? _cts;
    private Thread? _listenerThread;

    public void Start()
    {
        if (_listener is not null) return;

        _cts = new CancellationTokenSource();
        _listener = new HttpListener();
        _listener.Prefixes.Add(Prefix);
        _listener.Start();

        _listenerThread = new Thread(AcceptLoop) { IsBackground = true, Name = "STS2-API-Server" };
        _listenerThread.Start();

        MainFile.Logger.Info($"API server started on {Prefix}");
    }

    public void Stop()
    {
        _cts?.Cancel();
        _listener?.Stop();
        _listener?.Close();
        _listener = null;
        _cts = null;
        MainFile.Logger.Info("API server stopped.");
    }

    private async void AcceptLoop()
    {
        while (_listener is not null && _listener.IsListening && _cts is { IsCancellationRequested: false })
        {
            try
            {
                var context = await _listener.GetContextAsync();
                _ = HandleRequestAsync(context);
            }
            catch (ObjectDisposedException)
            {
                break;
            }
            catch (HttpListenerException)
            {
                break;
            }
        }
    }

    private async Task HandleRequestAsync(HttpListenerContext context)
    {
        var request = context.Request;
        var response = context.Response;

        response.ContentType = "application/json";
        response.AddHeader("Access-Control-Allow-Origin", "*");

        try
        {
            var (statusCode, body) = await RouteRequest(request);
            response.StatusCode = statusCode;
            var buffer = Encoding.UTF8.GetBytes(body);
            response.ContentLength64 = buffer.Length;
            await response.OutputStream.WriteAsync(buffer);
        }
        catch (Exception ex)
        {
            response.StatusCode = 500;
            var error = Encoding.UTF8.GetBytes($"{{\"error\":\"{ex.Message}\"}}");
            response.ContentLength64 = error.Length;
            await response.OutputStream.WriteAsync(error);
        }
        finally
        {
            response.OutputStream.Close();
        }
    }

    private async Task<(int statusCode, string body)> RouteRequest(HttpListenerRequest request)
    {
        var path = request.Url?.AbsolutePath ?? "";
        var method = request.HttpMethod;

        return (method, path) switch
        {
            ("GET", "/health") => (200, StateHandler.GetHealth()),
            ("GET", "/game/state") => (200, await DispatchToMainThread(StateHandler.GetGameState)),
            ("GET", "/game/combat") => (200, await DispatchToMainThread(CombatHandler.GetCombatState)),
            ("GET", "/game/combat/piles") => (200, await DispatchToMainThread(CombatHandler.GetPiles)),
            ("GET", "/game/deck") => (200, await DispatchToMainThread(StateHandler.GetDeck)),
            ("GET", "/game/actions") => (200, await DispatchToMainThread(StateHandler.GetAvailableActions)),
            ("GET", "/game/map") => (200, await DispatchToMainThread(MapHandler.GetMap)),
            ("POST", "/game/action/combat") => await HandleCombatAction(request),
            ("POST", "/game/action") => await HandleAction(request),
            _ => (404, "{\"error\":\"Not found\"}")
        };
    }

    private static async Task<(int, string)> HandleCombatAction(HttpListenerRequest request)
    {
        using var reader = new StreamReader(request.InputStream, request.ContentEncoding);
        var body = await reader.ReadToEndAsync();
        var result = await RequestDispatcher.Instance.EnqueueAsyncRequest(() => CombatActionHandler.HandleAction(body));
        return (200, result);
    }

    private static async Task<(int, string)> HandleAction(HttpListenerRequest request)
    {
        using var reader = new StreamReader(request.InputStream, request.ContentEncoding);
        var body = await reader.ReadToEndAsync();
        var result = await RequestDispatcher.Instance.EnqueueAsyncRequest(() => ActionHandler.HandleAction(body));
        return (200, result);
    }

    private static Task<string> DispatchToMainThread(Func<string> handler)
    {
        return RequestDispatcher.Instance.EnqueueRequest(handler);
    }
}

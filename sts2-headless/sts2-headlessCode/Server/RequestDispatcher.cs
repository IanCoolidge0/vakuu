using System.Collections.Concurrent;

namespace sts2_headless.sts2_headlessCode.Server;

public class RequestDispatcher
{
    public static RequestDispatcher Instance { get; } = new();

    private readonly ConcurrentQueue<PendingRequest> _syncQueue = new();
    private readonly ConcurrentQueue<PendingAsyncRequest> _asyncQueue = new();

    public Task<string> EnqueueRequest(Func<string> handler)
    {
        var tcs = new TaskCompletionSource<string>(TaskCreationOptions.RunContinuationsAsynchronously);
        _syncQueue.Enqueue(new PendingRequest(handler, tcs));
        return tcs.Task;
    }

    public Task<string> EnqueueAsyncRequest(Func<Task<string>> handler)
    {
        var tcs = new TaskCompletionSource<string>(TaskCreationOptions.RunContinuationsAsynchronously);
        _asyncQueue.Enqueue(new PendingAsyncRequest(handler, tcs));
        return tcs.Task;
    }

    /// <summary>
    /// Called from Godot's main thread in _Process(). Drains all pending requests.
    /// </summary>
    public void ProcessPendingRequests()
    {
        while (_syncQueue.TryDequeue(out var pending))
        {
            try
            {
                var result = pending.Handler();
                pending.Completion.SetResult(result);
            }
            catch (Exception ex)
            {
                pending.Completion.SetException(ex);
            }
        }

        while (_asyncQueue.TryDequeue(out var pending))
        {
            // Start the async handler on the main thread; when it completes, set the TCS result
            var tcs = pending.Completion;
            var task = pending.Handler();
            task.ContinueWith(t =>
            {
                if (t.IsFaulted)
                    tcs.SetException(t.Exception!.InnerExceptions);
                else
                    tcs.SetResult(t.Result);
            }, TaskContinuationOptions.ExecuteSynchronously);
        }
    }

    private record PendingRequest(Func<string> Handler, TaskCompletionSource<string> Completion);
    private record PendingAsyncRequest(Func<Task<string>> Handler, TaskCompletionSource<string> Completion);
}

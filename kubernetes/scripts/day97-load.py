#!/usr/bin/env python3
"""Bounded GET-only load of the lab's API Service. No credentials or DB writes."""
import argparse
import asyncio
import collections
import json
import signal
import time


def settings(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--rps', type=int, default=200)
    parser.add_argument('--seconds', type=int, default=540)
    parser.add_argument('--concurrency', type=int, default=16)
    args = parser.parse_args(argv)
    if not (1 <= args.rps <= 400 and 1 <= args.seconds <= 600
            and 1 <= args.concurrency <= 32):
        parser.error('Limits: 1-400 RPS, 1-600 seconds, 1-32 concurrent requests.')
    return args


async def main(args):
    import httpx  # Already installed in the existing application image.
    loop = asyncio.get_running_loop()
    stop = asyncio.Event()
    for sig in (signal.SIGINT, signal.SIGTERM):
        loop.add_signal_handler(sig, stop.set)
    counts = collections.Counter()
    queue = asyncio.Queue(maxsize=args.concurrency)
    started = time.monotonic()

    async with httpx.AsyncClient(
        timeout=5.0, trust_env=False,
        limits=httpx.Limits(max_connections=args.concurrency,
                           max_keepalive_connections=0),
    ) as client:
        async def worker():
            while True:
                item = await queue.get()
                if item is None:
                    queue.task_done()
                    return
                try:
                    # Reconnect so new Service backends can receive new flows.
                    response = await client.get('http://meeps-api/openapi.json',
                                                headers={'Connection': 'close'})
                    counts[str(response.status_code)] += 1
                except httpx.HTTPError:
                    counts['request_error'] += 1
                finally:
                    queue.task_done()

        workers = [asyncio.create_task(worker()) for _ in range(args.concurrency)]
        report_at = started + 10
        while not stop.is_set() and time.monotonic() - started < args.seconds:
            tick = time.monotonic()
            try:
                queue.put_nowait(1)
            except asyncio.QueueFull:
                counts['offered_request_skipped'] += 1
            if tick >= report_at:
                print(json.dumps({'elapsed_seconds': round(tick-started, 1),
                                  'target_rps': args.rps, 'counts': dict(counts)}),
                      flush=True)
                report_at = tick + 10
            # Do not catch up by bursting after scheduling delays.
            await asyncio.sleep(max(0.0, 1.0 / args.rps - (time.monotonic()-tick)))
        await queue.join()
        for _ in workers:
            await queue.put(None)
        await asyncio.gather(*workers)
    print(json.dumps({'finished': True, 'elapsed_seconds': round(time.monotonic()-started, 1),
                      'counts': dict(counts)}), flush=True)


if __name__ == '__main__':
    asyncio.run(main(settings()))

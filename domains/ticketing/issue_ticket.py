import json
import redis
import os

REDIS_HOST = os.environ.get('REDIS_HOST', '')
REDIS_PORT = int(os.environ.get('REDIS_PORT', 6379))

def lambda_handler(event, context):
    event_id = event.get('event_id', 'test-event')
    user_id = event.get('user_id', '')

    r = redis.Redis(host=REDIS_HOST, port=REDIS_PORT, decode_responses=True)

    cache_key = f"{event_id}:{user_id}"
    queue_number = r.incr(f"queue:{event_id}")

    if not r.set(cache_key, queue_number, nx=True, ex=3600):
        queue_number = int(r.get(cache_key))

    current_number = int(r.get(f"current:{event_id}") or 0)
    remaining = queue_number - current_number

    print(f"user_id={user_id}, event_id={event_id}, queue_number={queue_number}, remaining={remaining}")

    return {
        'statusCode': 200,
        'body': json.dumps({
            'message': '현재 대기열',
            'queue_number': queue_number,
            'remaining': remaining
        }, ensure_ascii=False)
    }
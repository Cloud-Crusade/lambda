import json
import redis
import os
import logging

import jwt

logger = logging.getLogger()
logger.setLevel(logging.INFO)

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

    logger.info(f"user_id={user_id}, event_id={event_id}, queue_number={queue_number}, remaining={remaining}")
    
    if remaining <= 0:
        logger.debug(f"티켓 발급: user_id={user_id}, event_id={event_id}")
        
        jwt_token = jwt.encode({'user_id': user_id, 'event_id': event_id, 'aud': 'reservation_waiting'}, 'secret', algorithm='HS256')
        return {
            'statusCode': 200,
            'body': json.dumps({
                'code': 'COMPLETED',
                'message': '입장 순번이 되었습니다.',
                'data': {
                    'token': jwt_token
                }
            }, ensure_ascii=False)
        }

    return {
        'statusCode': 200,
        'body': json.dumps({
            'code': 'WAITING',
            'message': '현재 대기열',
            'data': {
            'queue_number': queue_number,
                'remaining': remaining
            }
        }, ensure_ascii=False)
    }
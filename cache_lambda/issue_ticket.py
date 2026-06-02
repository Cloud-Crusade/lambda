import json
import uuid
import redis
import os
import urllib.request

REDIS_HOST = os.environ.get('REDIS_HOST', '')
REDIS_PORT = int(os.environ.get('REDIS_PORT', 6379))
EKS_ENDPOINT = os.environ.get('EKS_ENDPOINT', '')  # 팀 인프라 완성 후 환경변수로 설정

def lambda_handler(event, context):
    action = event.get('action', 'register')
    event_id = event.get('event_id', 'test-event')

    r = redis.Redis(host=REDIS_HOST, port=REDIS_PORT, decode_responses=True)

    # ① 번호표 발급 + Redis 대기열 등록 (테스트 완료 ✅)
    if action == 'register':
        session_id = str(uuid.uuid4())
        cache_key = f"setnx:{event_id}:{session_id}"
        queue_number = r.incr(f"queue:{event_id}")
        r.set(cache_key, queue_number, nx=True, ex=3600)

        return {
            'statusCode': 200,
            'body': json.dumps({
                'message': '대기열에 등록되었습니다',
                'session_id': session_id,
                'event_id': event_id,
                'cache_key': cache_key,
                'queue_number': queue_number
            }, ensure_ascii=False)
        }

    # ② 순번 확인 → 내 차례면 EKS로 전달
    elif action == 'check':
        session_id = event.get('session_id', '')
        my_number = int(event.get('queue_number', 0))
        current_number = int(r.get(f"current:{event_id}") or 0)
        remaining = my_number - current_number

        if remaining <= 0:
            # EKS로 요청 전달 (EKS_ENDPOINT 환경변수 설정 후 동작)
            if EKS_ENDPOINT:
                eks_payload = json.dumps({
                    'session_id': session_id,
                    'event_id': event_id
                }).encode('utf-8')

                req = urllib.request.Request(
                    EKS_ENDPOINT,
                    data=eks_payload,
                    headers={'Content-Type': 'application/json'},
                    method='POST'
                )
                urllib.request.urlopen(req)

            return {
                'statusCode': 200,
                'body': json.dumps({
                    'message': '입장 가능합니다. EKS로 전달되었습니다.',
                    'session_id': session_id,
                    'status': 'admitted'
                }, ensure_ascii=False)
            }
        else:
            return {
                'statusCode': 200,
                'body': json.dumps({
                    'message': '대기 중입니다',
                    'session_id': session_id,
                    'remaining': remaining,
                    'status': 'waiting'
                }, ensure_ascii=False)
            }

    else:
        return {
            'statusCode': 400,
            'body': json.dumps({'message': 'action 값이 올바르지 않습니다'}, ensure_ascii=False)
        }
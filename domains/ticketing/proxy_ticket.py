import json
import os
import logging
import urllib.request
import urllib.error

import jwt

logger = logging.getLogger()
logger.setLevel(logging.INFO)

JWT_SECRET = os.environ.get('JWT_SECRET', 'secret')
JWT_ALGORITHM = os.environ.get('JWT_ALGORITHM', 'HS256')
WAS_ENDPOINT = os.environ.get('WAS_ENDPOINT', '')


def _forbidden(message):
    return {
        'statusCode': 403,
        'body': json.dumps({
            'code': 'FORBIDDEN',
            'message': message
        }, ensure_ascii=False)
    }


def _parse_body(event):
    body = event.get('body')
    if isinstance(body, str) and body:
        try:
            return json.loads(body)
        except json.JSONDecodeError:
            return {}
    if isinstance(body, dict):
        return body
    return {}


def _extract_token(event, body):
    headers = event.get('headers') or {}
    auth = headers.get('Authorization') or headers.get('authorization') or ''
    if auth:
        return auth.replace('Bearer', '').strip()
    return event.get('jwt_token') or body.get('jwt_token', '')


def lambda_handler(event, context):
    body = _parse_body(event)

    jwt_token = _extract_token(event, body)
    target_user_id = event.get('user_id') or body.get('user_id', '')
    target_event_id = event.get('event_id') or body.get('event_id', '')

    if not jwt_token:
        logger.info("토큰 없음")
        return _forbidden('토큰이 없습니다.')

    # JWT 해체 및 검증
    try:
        payload = jwt.decode(jwt_token, JWT_SECRET, algorithms=[JWT_ALGORITHM])
    except jwt.PyJWTError as error:
        logger.info(f"토큰 검증 실패: {error}")
        return _forbidden('유효하지 않은 토큰입니다.')

    token_user_id = payload.get('user_id', '')
    token_event_id = payload.get('event_id', '')

    # token 정보가 요청 대상과 일치하는지 확인
    if token_user_id != target_user_id or token_event_id != target_event_id:
        logger.info(
            f"불일치: token=({token_user_id}, {token_event_id}), "
            f"target=({target_user_id}, {target_event_id})"
        )
        return _forbidden('요청 대상과 토큰 정보가 일치하지 않습니다.')

    # 검증 통과 시 WAS로 전달
    logger.info(f"검증 성공, WAS 전달: user_id={token_user_id}, event_id={token_event_id}")
    return _forward_to_was(body, jwt_token)


def _forward_to_was(body, jwt_token):
    data = json.dumps(body).encode('utf-8')
    request = urllib.request.Request(
        WAS_ENDPOINT,
        data=data,
        headers={
            'Content-Type': 'application/json',
            'Authorization': f'Bearer {jwt_token}'
        },
        method='POST'
    )

    try:
        with urllib.request.urlopen(request, timeout=5) as response:
            return {
                'statusCode': response.status,
                'body': response.read().decode('utf-8')
            }
    except urllib.error.HTTPError as error:
        return {
            'statusCode': error.code,
            'body': error.read().decode('utf-8')
        }
    except urllib.error.URLError as error:
        logger.error(f"WAS 전달 실패: {error}")
        return {
            'statusCode': 502,
            'body': json.dumps({
                'code': 'BAD_GATEWAY',
                'message': 'WAS 연결에 실패했습니다.'
            }, ensure_ascii=False)
        }

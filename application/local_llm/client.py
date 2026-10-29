"""Ollama local GGUF model discovery and unapproved account candidates."""
from .config import DEFAULT_ENDPOINT, parse_json, timeout_value, validate_endpoint, validate_model
from .errors import LocalLlmError
from .prompts import PROMPT_VERSION, build_payload, prepare_inputs, text, validate_candidates
from .transport import request_json


def _local_model(item):
    if not isinstance(item, dict) or item.get('remote_host') or item.get('remote_model'):
        return None
    try:
        name = validate_model(item.get('name'))
        details = item.get('details', {})
        size = item.get('size')
        if not isinstance(details, dict) or type(size) is not int or size < 1024 * 1024:
            return None
        if details.get('format') != 'gguf':
            return None
        digest = text(item.get('digest'), '모델 지문', 200)
        return {'name': name, 'digest': digest, 'size': size,
                'parameterSize': str(details.get('parameter_size', ''))[:100],
                'quantization': str(details.get('quantization_level', ''))[:100]}
    except LocalLlmError:
        return None


def list_models(endpoint=DEFAULT_ENDPOINT, timeout=5):
    value = request_json(endpoint, '/api/tags', timeout=timeout)
    models = value.get('models')
    if not isinstance(models, list) or len(models) > 1000:
        raise LocalLlmError('Ollama 설치 모델 목록의 형식을 확인해 주세요.')
    result = []
    for item in models:
        model = _local_model(item)
        if model is not None:
            result.append(model)
    if len({model['name'] for model in result}) != len(result):
        raise LocalLlmError('Ollama 모델 목록에 같은 이름이 반복돼요. 실행 중인 서버를 확인해 주세요.')
    return sorted(result, key=lambda model: model['name'])


def _verify_local_model(endpoint, model, timeout):
    selected = next((item for item in list_models(endpoint, timeout=min(timeout, 10)) if item['name'] == model), None)
    if selected is None:
        raise LocalLlmError('선택한 모델의 로컬 가중치를 찾지 못했어요. 설치 모델 목록에서 다시 선택해 주세요.')
    show = request_json(endpoint, '/api/show', {'model': model, 'verbose': False}, timeout=min(timeout, 15))
    if show.get('remote_host') or show.get('remote_model'):
        raise LocalLlmError('원격·Cloud 모델에는 계정 정보를 보내지 않아요. 로컬 가중치 모델을 선택해 주세요.')
    info, details = show.get('model_info'), show.get('details')
    capabilities = show.get('capabilities', [])
    if (not isinstance(info, dict) or not isinstance(details, dict) or not isinstance(capabilities, list)
            or details.get('format') != 'gguf' or not info.get('general.architecture')
            or ('completion' not in capabilities)):
        raise LocalLlmError('로컬 텍스트 생성 모델의 가중치 정보를 확인하지 못했어요. 다른 설치 모델을 선택해 주세요.')
    return selected


def recommend_accounts(source, accounts, *, model, endpoint=DEFAULT_ENDPOINT, rejected=(), timeout=120):
    """Return exactly three candidates without changing mappings or approvals."""
    endpoint = validate_endpoint(endpoint)
    model = validate_model(model)
    timeout = timeout_value(timeout)
    selected, available, fingerprint = prepare_inputs(source, accounts, rejected)
    installed = _verify_local_model(endpoint, model, timeout)
    payload = build_payload(selected, available, model)
    value = request_json(endpoint, '/api/chat', payload, timeout=timeout)
    if value.get('remote_host') or value.get('remote_model'):
        raise LocalLlmError('로컬 추론 응답이 아니어서 추천을 적용하지 않았어요.')
    if value.get('model') != model:
        raise LocalLlmError('선택한 모델과 응답 모델이 달라서 추천을 적용하지 않았어요.')
    if value.get('done') is not True or value.get('done_reason') == 'length':
        raise LocalLlmError('로컬 LLM 응답이 완료되지 않았어요. 다른 모델이나 대기 시간을 선택해 주세요.')
    message = value.get('message')
    if not isinstance(message, dict) or message.get('role') != 'assistant' or message.get('tool_calls'):
        raise LocalLlmError('로컬 LLM의 후보 응답을 읽을 수 없어요.')
    content = text(message.get('content'), '모델 응답', 10000)
    candidates = validate_candidates(parse_json(content), available)
    return {'candidates': candidates, 'provider': 'ollama', 'model': model,
            'endpoint': endpoint, 'modelDigest': installed['digest'], 'promptVersion': PROMPT_VERSION,
            'inputFingerprint': fingerprint, 'approved': False,
            'transport': value.get('_localClientRetry', {'attempts': 1, 'retryReasons': []})}

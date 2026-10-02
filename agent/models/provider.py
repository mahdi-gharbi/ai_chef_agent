"""Reuse existing model wrappers; no OpenAI adapter or API dependency."""
import os
from services.errors import KookiError


def provider_name(config):
    override = os.environ.get('KOOKI_PROVIDER')
    if override:
        if override not in {'gemini', 'qwen', 'ollama'}:
            raise KookiError('MODEL_CONFIGURATION_ERROR')
        return override
    if config.get('lora', {}).get('use_lora_adapter'):
        return 'ollama'
    return 'gemini' if config.get('gemini', {}).get('use_gemini') else 'qwen'


def create_provider(config):
    name = provider_name(config)
    if name == 'ollama':
        from agent.models.local_model import LocalChefModel
        local = dict(config.get('lora', {}))
        local['ollama_model'] = os.environ.get('KOOKI_OLLAMA_MODEL', local.get('ollama_model', 'qwen2.5:7b'))
        local['ollama_base_url'] = os.environ.get('KOOKI_OLLAMA_BASE_URL', local.get('ollama_base_url', 'http://localhost:11434'))
        return name, LocalChefModel(local).llm
    required = 'GEMINI_API_KEY' if name == 'gemini' else 'DASHSCOPE_API_KEY'
    if not os.environ.get(required):
        raise KookiError('MODEL_CONFIGURATION_ERROR')
    if name == 'gemini':
        from agent.models.gemini_model import GeminiChefModel
        return name, GeminiChefModel(config.get('gemini', {})).llm
    from agent.models.cloud_model import CloudChefModel
    return name, CloudChefModel(config.get('llm', {})).llm

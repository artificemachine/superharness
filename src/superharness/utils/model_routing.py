"""Model routing utilities for agent adapters."""

def apply_model_prefix(model: str) -> str:
    """Apply provider prefix to model ID if not already present.
    
    Used by adapters (like OpenCode) that expect 'provider/model' format.
    """
    if not model or "/" in model:
        return model
        
    if model.startswith("claude-"):
        return f"anthropic/{model}"
    elif model.startswith(("gpt-", "o1-", "o3-")):
        return f"openai/{model}"
    elif model.startswith("gemini-"):
        return f"google/{model}"
    elif model.startswith("deepseek-"):
        return f"deepseek/{model}"
        
    return model

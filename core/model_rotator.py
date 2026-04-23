import itertools

class ModelRotator:
    """
    Manages round-robin rotation of OpenRouter free models to avoid rate limits.
    """
    
    FREE_MODELS = [
        "qwen/qwen3-235b-a22b:free",                    # Qwen3 235B - MASSIVE reasoning model
        "deepseek/deepseek-r1-0528-qwen3-8b:free",      # DeepSeek R1 - Reasoning specialist
        "qwen/qwen-2.5-72b-instruct:free",              # Qwen 2.5 72B - Large versatile
        "qwen/qwen-2.5-coder-32b-instruct:free",        # Qwen Coder - Code/exploit specialist
        "qwen/qwen2.5-vl-32b-instruct:free",            # Qwen VL - Vision capabilities
        "x-ai/grok-4.1-fast:free",                      # Grok 4.1 - Fast analysis
        "google/gemini-2.0-flash-exp:free",             # Gemini 2.0 - Experimental features
        "tngtech/deepseek-r1t2-chimera:free",           # DeepSeek Chimera - Reasoning
    ]
    
    def __init__(self):
        self.counter = 0
        self.cycle = itertools.cycle(self.FREE_MODELS)
        
    def get_next_model(self):
        """Returns the next model in rotation."""
        model = next(self.cycle)
        self.counter += 1
        return model
    
    def get_current_count(self):
        """Returns how many times rotation has occurred."""
        return self.counter
    
    def reset(self):
        """Resets the rotation counter."""
        self.counter = 0
        self.cycle = itertools.cycle(self.FREE_MODELS)

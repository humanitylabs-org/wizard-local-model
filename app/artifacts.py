"""Immutable provisioning catalogue; mirrored in wizard.md, never caller supplied."""
CATALOG = [
    {'id':'qwen2.5-1.5b','label':'Qwen2.5 1.5B Instruct (recommended)', 'size':1117320736,
     'repo':'Qwen/Qwen2.5-1.5B-Instruct-GGUF','revision':'91cad51170dc346986eccefdc2dd33a9da36ead9',
     'file':'qwen2.5-1.5b-instruct-q4_k_m.gguf','sha256':'6a1a2eb6d15622bf3c96857206351ba97e1af16c30d7a74ee38970e434e9407e'},
    {'id':'qwen2.5-3b','label':'Qwen2.5 3B Instruct', 'size':2104932768,
     'repo':'Qwen/Qwen2.5-3B-Instruct-GGUF','revision':'7dabda4d13d513e3e842b20f0d435c732f172cbe',
     'file':'qwen2.5-3b-instruct-q4_k_m.gguf','sha256':'626b4a6678b86442240e33df819e00132d3ba7dddfe1cdc4fbb18e0a9615c62d'},
    {'id':'qwen2.5-0.5b','label':'Qwen2.5 0.5B Instruct (small test)', 'size':491400032,
     'repo':'Qwen/Qwen2.5-0.5B-Instruct-GGUF','revision':'9217f5db79a29953eb74d5343926648285ec7e67',
     'file':'qwen2.5-0.5b-instruct-q4_k_m.gguf','sha256':'74a4da8c9fdbcd15bd1f6d01d621410d31c6fc00986f5eb687824e7b93d7a9db'},
]

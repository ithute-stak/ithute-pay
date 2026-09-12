from pathlib import Path


def _read_optional(value: str | None, path: str | None) -> str | None:
    if value:
        return value.replace('\\n', '\n')
    if path:
        return Path(path).expanduser().read_text(encoding='utf-8')
    return None


def load_keys(settings) -> tuple[str, str]:
    """Resolve JWT signing keys while retaining easy HS256 development setup."""
    algorithm = settings.ALGORITHM.upper()
    if algorithm.startswith('HS'):
        return settings.SECRET_KEY, settings.SECRET_KEY

    private_key = _read_optional(settings.JWT_PRIVATE_KEY, settings.JWT_PRIVATE_KEY_PATH)
    public_key = _read_optional(settings.JWT_PUBLIC_KEY, settings.JWT_PUBLIC_KEY_PATH)
    if not private_key or not public_key:
        raise RuntimeError(
            'JWT_PRIVATE_KEY/JWT_PUBLIC_KEY (or their *_PATH settings) are required '
            f'when ALGORITHM={settings.ALGORITHM}'
        )
    return private_key, public_key

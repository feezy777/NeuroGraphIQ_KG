"""Schemas for local Workbench runtime settings.

Settings are local operational configuration only. They never write candidate,
final_*, or kg_* data, and public response models never expose API keys.
"""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field, model_validator


class DeepSeekRuntimeSettings(BaseModel):
    enabled: bool = True
    base_url: str = "https://api.deepseek.com/v1"
    default_model: str = "deepseek-chat"
    api_key: str = ""
    timeout_seconds: int = Field(default=30, ge=5, le=120)
    max_batch_size: int = Field(default=20, ge=1, le=20)
    temperature: float = Field(default=0.2, ge=0.0, le=2.0)
    max_tokens: int = Field(default=2000, ge=256, le=8192)


class KimiRuntimeSettings(BaseModel):
    enabled: bool = True
    base_url: str = "https://api.moonshot.cn/v1"
    default_model: str = "moonshot-v1-8k"
    api_key: str = ""
    timeout_seconds: int = Field(default=60, ge=5, le=120)
    max_batch_size: int = Field(default=20, ge=1, le=20)
    temperature: float = Field(default=0.2, ge=0.0, le=2.0)
    max_tokens: int = Field(default=2000, ge=256, le=8192)


class ApiProviderRuntimeSettings(BaseModel):
    deepseek: DeepSeekRuntimeSettings = Field(default_factory=DeepSeekRuntimeSettings)
    kimi: KimiRuntimeSettings = Field(default_factory=KimiRuntimeSettings)


class BasicRuntimeSettings(BaseModel):
    default_page_size: int = Field(default=50, ge=10, le=200)
    max_page_size: int = Field(default=500, ge=50, le=500)
    show_debug_panels: bool = True

    @model_validator(mode="after")
    def validate_page_sizes(self):
        if self.max_page_size < self.default_page_size:
            raise ValueError("max_page_size must be greater than or equal to default_page_size")
        return self


class RuntimeSettings(BaseModel):
    api_providers: ApiProviderRuntimeSettings = Field(
        default_factory=ApiProviderRuntimeSettings
    )
    basic: BasicRuntimeSettings = Field(default_factory=BasicRuntimeSettings)


class PublicDeepSeekRuntimeSettings(BaseModel):
    enabled: bool
    base_url: str
    default_model: str
    api_key_configured: bool
    api_key_masked: str | None
    timeout_seconds: int
    max_batch_size: int
    temperature: float = 0.2
    max_tokens: int = 2000


class PublicKimiRuntimeSettings(BaseModel):
    enabled: bool
    base_url: str
    default_model: str
    api_key_configured: bool
    api_key_masked: str | None
    timeout_seconds: int
    max_batch_size: int
    temperature: float = 0.2
    max_tokens: int = 2000


class PublicApiProviderRuntimeSettings(BaseModel):
    deepseek: PublicDeepSeekRuntimeSettings
    kimi: PublicKimiRuntimeSettings


class PublicRuntimeSettings(BaseModel):
    api_providers: PublicApiProviderRuntimeSettings
    basic: BasicRuntimeSettings


class DeepSeekRuntimeSettingsPatch(BaseModel):
    enabled: bool | None = None
    base_url: str | None = None
    default_model: str | None = None
    api_key: str | None = None
    explicit_clear_api_key: bool = False
    timeout_seconds: int | None = Field(default=None, ge=5, le=120)
    max_batch_size: int | None = Field(default=None, ge=1, le=20)
    temperature: float | None = Field(default=None, ge=0.0, le=2.0)
    max_tokens: int | None = Field(default=None, ge=256, le=8192)


class KimiRuntimeSettingsPatch(BaseModel):
    enabled: bool | None = None
    base_url: str | None = None
    default_model: str | None = None
    api_key: str | None = None
    explicit_clear_api_key: bool = False
    timeout_seconds: int | None = Field(default=None, ge=5, le=120)
    max_batch_size: int | None = Field(default=None, ge=1, le=20)
    temperature: float | None = Field(default=None, ge=0.0, le=2.0)
    max_tokens: int | None = Field(default=None, ge=256, le=8192)


class ApiProviderRuntimeSettingsPatch(BaseModel):
    deepseek: DeepSeekRuntimeSettingsPatch | None = None
    kimi: KimiRuntimeSettingsPatch | None = None


class BasicRuntimeSettingsPatch(BaseModel):
    default_page_size: int | None = Field(default=None, ge=10, le=200)
    max_page_size: int | None = Field(default=None, ge=50, le=500)
    show_debug_panels: bool | None = None


class RuntimeSettingsPatch(BaseModel):
    api_providers: ApiProviderRuntimeSettingsPatch | None = None
    basic: BasicRuntimeSettingsPatch | None = None


class SettingsLanguageOption(BaseModel):
    value: str
    label: str


class SettingsProviderOption(BaseModel):
    value: str
    label: str
    disabled: bool = False


class SettingsOptions(BaseModel):
    languages: list[SettingsLanguageOption]
    api_providers: list[SettingsProviderOption]
    default_models: dict[str, list[str]]


class DeepSeekConnectionTestRequest(BaseModel):
    base_url: str | None = None
    default_model: str | None = None
    api_key: str | None = None


class DeepSeekConnectionTestResponse(BaseModel):
    ok: bool
    provider: str = "deepseek"
    model: str | None = None
    latency_ms: int | None = None
    error_message: str | None = None


class DeepSeekRuntimeConfig(BaseModel):
    """Resolved internal DeepSeek config; may contain a secret."""

    model_config = ConfigDict(frozen=True)

    enabled: bool
    base_url: str
    default_model: str
    api_key: str
    timeout_seconds: int
    max_batch_size: int
    temperature: float = 0.2
    max_tokens: int = 2000


class KimiRuntimeConfig(BaseModel):
    """Resolved internal Kimi config; may contain a secret."""

    model_config = ConfigDict(frozen=True)

    enabled: bool
    base_url: str
    default_model: str
    api_key: str
    timeout_seconds: int
    max_batch_size: int
    temperature: float = 0.2
    max_tokens: int = 2000

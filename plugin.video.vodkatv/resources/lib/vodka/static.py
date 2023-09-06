from base64 import b64decode
from functools import wraps

from Cryptodome.Cipher import AES
from Cryptodome.Util.Padding import unpad

from .enums import DeviceBrandId

_key = bytes.fromhex("766f646b617476706173737772640202")
_iv = bytes.fromhex("e81b70e7ea32d0d781e3294740a2f288")

user_agent = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36"
config_platform_os = "pc"
locale_language = "hu"
locale_country = "null"
locale_device = "null"
locale_user_state = "Unknown"
platform = "Web"
provider_id = "-1"
device_brand_id = DeviceBrandId.PCMAC.value
api_version = "5.2"
channel_type = "519"
channel_id = 100347432
media_file_ids = ["Web_Secondary_HD", "Web_Secondary_SD"]
npvr_types = {"Web_Secondary_HD": "NPVR_TYPE_968", "Web_Secondary_SD": "NPVR_TYPE_960"}
recordable = "w_npvr=1"
restartable = "w_restart=1"

cache = {}


def cache_result(func):
    @wraps(func)
    def wrapper(*args, **kwargs):
        # Generate a cache key based on function name and arguments
        cache_key = (func.__name__, args, frozenset(kwargs.items()))

        # Check if the result is already in the cache
        if cache_key in cache:
            return cache[cache_key]

        # If not in cache, compute the result and store it
        result = func(*args, **kwargs)
        cache[cache_key] = result
        return result

    return wrapper


def _decrypt_string(input: str) -> str:
    """
    Decrypts a string using AES-128-CBC with PKCS7 padding

    :param input: Encrypted string
    :return: Decrypted string
    """
    cipher = AES.new(_key, AES.MODE_CBC, _iv)
    return unpad(cipher.decrypt(b64decode(input)), 16, style="pkcs7").decode("utf-8")


@cache_result
def get_config_js() -> str:
    c = "9VMCHYuj5N/qQTYlgCfVwCsKhz45Z1whPLYofKxInlwzuxLwOLbODBL8nf/c5RgD"
    return _decrypt_string(c)


@cache_result
def get_ott_platform_name() -> str:
    c = "U5LD2nPCH1Q9PCSvcYBw+w=="
    return _decrypt_string(c)


if __name__ == "__main__":
    print("get_config_js:\t", get_config_js())
    print("get_ott_platform_name:\t", get_ott_platform_name())

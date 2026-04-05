import hashlib
import hmac
import secrets
import string
from base64 import b64decode
from base64 import b64encode
from base64 import urlsafe_b64encode

from cryptography.fernet import Fernet
from django.conf import settings


def calc_hmac(message: str, key: str) -> str:
    return hmac.new(key.encode(), message.encode(), hashlib.sha256).hexdigest()


def verify_hmac(message: str, key: str, signature: str) -> bool:
    calculated_hmac = calc_hmac(message, key)
    return hmac.compare_digest(signature, calculated_hmac)


class AESCipher:
    def __init__(self, key: str):
        bytes_key = urlsafe_b64encode(hashlib.sha256(key.encode()).digest())
        self.fernet = Fernet(bytes_key)

    def encrypt(self, message: str) -> str:
        """加密数据"""
        encrypted_text = self.fernet.encrypt(message.encode())
        return b64encode(encrypted_text).decode()

    def decrypt(self, message: str) -> str:
        """解密数据"""
        decrypted_text = self.fernet.decrypt(b64decode(message.encode()))
        return decrypted_text.decode()


def generate_random_code(
    *,
    length=16,
    readable=False,
    uppercase_only=False,
    lowercase_only=False,
    include_numbers=True,
):
    """
    生成随机字符串

    参数:
        length (int): 字符串长度，默认16
        readable (bool): 是否排除容易混淆的字符，默认False
        uppercase_only (bool): 是否只使用大写字母，默认False
        lowercase_only (bool): 是否只使用小写字母，默认False
        include_numbers (bool): 是否包含数字，默认True

    返回:
        str: 生成的随机字符串

    注意:
        - uppercase_only 和 lowercase_only 不能同时为 True
        - 如果都为 False，则使用大小写混合
    """

    # 参数验证
    if uppercase_only and lowercase_only:
        raise ValueError("uppercase_only 和 lowercase_only 不能同时为 True")

    # 构建字符集
    alphabet = ""

    # 根据大小写选项构建字母字符集
    if uppercase_only:
        alphabet += string.ascii_uppercase
    elif lowercase_only:
        alphabet += string.ascii_lowercase
    else:
        alphabet += string.ascii_letters

    # 根据选项添加数字
    if include_numbers:
        alphabet += string.digits

    # 如果字符集为空，抛出异常
    if not alphabet:
        raise ValueError("字符集不能为空，请至少选择一种字符类型")

    # 如果需要可读性，移除容易混淆的字符
    if readable:
        # 定义容易混淆的字符（更完整的列表）
        confusing_chars = "0oOIl1B8G6bpqd2Z5S"
        # 0 - 数字零，容易与字母 O 混淆
        # o - 小写字母，容易与数字 0 和大写字母 O 混淆
        # O - 大写字母，容易与数字 0 和小写字母 o 混淆
        # I - 大写字母 i，容易与小写字母 l 和数字 1 混淆
        # l - 小写字母 L，容易与大写字母 I 和数字 1 混淆
        # 1 - 数字一，容易与字母 I 和 l 混淆
        # B - 大写字母，容易与数字 8 混淆
        # 8 - 数字八，容易与字母 B 混淆
        # G - 大写字母，容易与数字 6 混淆
        # 6 - 数字六，容易与字母 G 混淆
        # b - 小写字母，容易与数字 6 混淆
        # p - 小写字母，容易与字母 q 混淆
        # q - 小写字母，容易与字母 p 混淆
        # d - 小写字母，容易与字母 b 混淆
        # 2 - 数字二，容易与字母 Z 混淆
        # Z - 大写字母，容易与数字 2 混淆
        # 5 - 数字五，容易与字母 S 混淆
        # S - 大写字母，容易与数字 5 混淆

        alphabet = "".join([char for char in alphabet if char not in confusing_chars])

        # 检查过滤后是否还有可用字符
        if not alphabet:
            raise ValueError("应用可读性过滤后没有可用字符，请调整参数")

    return "".join(secrets.choice(alphabet) for _ in range(length))


if __name__ != "__main__":
    aes_cipher = AESCipher(settings.SECRET_KEY)

else:
    pass

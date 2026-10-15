import binascii

from Crypto.Cipher import DES
from Crypto.Util.Padding import pad, unpad

# 秘钥
KEY = 'pityspwd'


class Des(object):

    @staticmethod
    def des_encrypt(s):
        """
        DES 加密
        :param s: 原始字符串
        :return: 加密后字符串,16进制

        替代 pyDes:pyDes 的 PAD_PKCS5 == pycryptodome 的 PKCS#7 pad/unpad
        (DES block_size=8 下两者等价),DES-CBC 输出二进制完全一致,
        旧的 16 进制密文可以被新代码 des_decrypt 正确解出。
        """
        secret_key = KEY.encode()  # 8 字节
        iv = secret_key  # 偏移
        cipher = DES.new(secret_key, DES.MODE_CBC, iv)
        # pad=s 编码后再做 PKCS#7 padding,长度对齐 8 字节
        ct = cipher.encrypt(pad(s.encode(), DES.block_size))
        # 返回为 16 进制
        return binascii.b2a_hex(ct).decode()

    @staticmethod
    def des_decrypt(s):
        """
        DES 解密
        :param s: 加密后的字符串,16 进制
        :return:  解密后的字符串
        """
        secret_key = KEY.encode()
        iv = secret_key
        cipher = DES.new(secret_key, DES.MODE_CBC, iv)
        plaintext = unpad(cipher.decrypt(binascii.a2b_hex(s)), DES.block_size)
        return plaintext.decode()

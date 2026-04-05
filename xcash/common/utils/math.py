from decimal import ROUND_HALF_UP
from decimal import Decimal


def round_decimal(d: Decimal, n: int, rounding=ROUND_HALF_UP) -> Decimal:
    """
    将一个 Decimal 对象按照指定规则进行精确舍入。

    函数采用标准的“四舍五入”规则 (ROUND_HALF_UP)。

    :param d: 需要处理的 Decimal 对象。
    :param n: 精度指示器。
              - n < 0: 精确到小数点后 |n| 位。
              - n > 0: 精确到小数点前 n 位 (即舍入到 10^n 的最接近整数倍)。
              - n = 0: 精确到最接近的整数。
    :param rounding: `decimal` 模块提供的舍入模式，默认四舍五入。
    :return: 经过精确舍入后的新 Decimal 对象。
    """
    # 根据 n 构建量化指数。
    # 例如:
    # n = 2  -> '1e2' -> Decimal('100')  (舍入到百位)
    # n = 0  -> '1e0' -> Decimal('1')    (舍入到个位)
    # n = -2 -> '1e-2'-> Decimal('0.01') (舍入到小数点后两位)
    quantizer = Decimal("1e" + str(n))

    # 使用 quantize 方法进行舍入
    # rounding=ROUND_HALF_UP 表示传统的四舍五入
    return d.quantize(quantizer, rounding=rounding)


def format_decimal_stripped(value: Decimal | None) -> str:
    """将 Decimal 转成普通字符串，并去掉末尾无意义的 0。"""
    if value is None:
        return ""

    normalized_value = value.normalize()
    # format(_, "f") 可避免 normalize() 输出科学计数法。
    formatted = format(normalized_value, "f")
    if formatted == "-0":
        return "0"
    return formatted

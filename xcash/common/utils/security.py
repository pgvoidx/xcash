import ipaddress


def is_ip_in_whitelist(whitelist: str | list, ip: str) -> bool:
    """
    检查 ip 参数是否在 whitelist 参数代表的白名单当中
    :param whitelist:
    :param ip:
    :return: bool, 当在则返回 True,否则返回 False
    """
    if "*" in whitelist:
        return True

    if isinstance(whitelist, str):
        whitelist = whitelist.split(",")

    ip_addr = ipaddress.ip_address(ip)
    for raw_item in whitelist:
        item = str(raw_item).strip()
        if not item:
            continue
        if "/" in item:  # 判断是否为网段
            ip_network = ipaddress.ip_network(item, strict=False)
            if ip_addr in ip_network:
                return True
        elif ip_addr == ipaddress.ip_address(item):
            return True

    return False


def is_ip_or_network(string: str) -> bool:
    try:
        ipaddress.ip_address(string)
    except ValueError:
        pass
    else:
        return True

    try:
        ipaddress.ip_network(string, strict=False)
    except ValueError:
        return False
    else:
        return True

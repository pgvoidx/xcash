from unfold.widgets import UnfoldAdminSelectWidget


class CurrencySelectWidget(UnfoldAdminSelectWidget):
    """法币/加密货币下拉框，通过颜色和 data 属性区分币种类型。"""

    FIAT_STYLE = "color:#1d4ed8;font-weight:600;"
    CRYPTO_STYLE = "color:#047857;font-weight:600;"

    def __init__(self, *, fiat_codes: set[str]):
        self._fiat_codes = {code.upper() for code in fiat_codes}
        super().__init__(attrs={"data-role": "currency-select"})

    def create_option(
        self, name, value, label, selected, index, subindex=None, attrs=None
    ):
        option = super().create_option(
            name, value, label, selected, index, subindex, attrs
        )
        if "options" in option:
            for sub_option in option["options"]:
                self._decorate_option(sub_option)
            return option
        return self._decorate_option(option)

    def _decorate_option(self, option: dict) -> dict:
        raw_value = option.get("value")
        if raw_value in (None, ""):
            return option

        value = str(raw_value).upper()
        attrs = option.setdefault("attrs", {})
        style = attrs.get("style", "")
        if value in self._fiat_codes:
            attrs["data-currency-type"] = "fiat"
            attrs["style"] = f"{style}{self.FIAT_STYLE}"
        else:
            attrs["data-currency-type"] = "crypto"
            attrs["style"] = f"{style}{self.CRYPTO_STYLE}"

        existing_class = attrs.get("class", "")
        attrs["class"] = f"{existing_class} currency-option".strip()
        return option

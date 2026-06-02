from discord import SeparatorSpacing
from discord.ui import Separator, Container


class Small_Separator(Separator):

    def __init__(self):

        super().__init__(
            visible=True,
            spacing=SeparatorSpacing.small,
        )


class Large_Separator(Separator):

    def __init__(self):

        super().__init__(
            visible=True,
            spacing=SeparatorSpacing.large,
        )


class Invisible_Separator(Separator):

    def __init__(
        self,
        spacing=SeparatorSpacing.small,
    ):

        super().__init__(
            visible=False,
            spacing=spacing,
        )

class Menu_Container(Container):
    def __init__(self, *items):
        children = []
        for index, item in enumerate(items):
            children.append(item)
            if index != len(items) - 1:
                children.append(Small_Separator())
        super().__init__(*children)
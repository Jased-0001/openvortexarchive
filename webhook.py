class Embed:
    """https://docs.discord.com/developers/developer-tools/embedded-app-sdk#embed"""

    def __init__(self, title: str, description: str) -> None:
        self.title:          str = title
        self.type:           str | None = None
        self.description:    str = description
        self.url:            str | None = None
        self.timestamp:      str | None = None
        self.color:          int | None = None

        self.footer:       EmbedFooter | None      = None
        self.provider:     EmbedProvider | None    = None
        self.author:       EmbedAuthor | None      = None
        self.fields:       list[EmbedField]        = []

        self.image:        str | None = None # IDK how these work
        # self.thumbnail:    str | None = None
        # self.video:        str | None = None

        pass

    def dictify_list(self, lst) -> list[dict]:
        newlist = []
        for i in lst: newlist.append(i.to_dict())
        return newlist
    
    def to_dict(self) -> dict[str, str | int | None | list[dict] | dict]:
        data = {}

        def add(key,value):
            if value:
                data[key] = value
        
        add(key="title",       value=self.title)
        add(key="type",        value=self.type)
        add(key="description", value=self.description)
        #add(key="url",         value=self.url) for some reason makes it so multiple embeds cannot be sent
        add(key="timestamp",   value=self.timestamp)
        add(key="color",       value=self.color)

        add(key="footer",      value=self.footer.to_dict()              if self.footer   else None)
        add(key="provider",    value=self.provider.to_dict()            if self.provider else None)
        add(key="author",      value=self.author.to_dict()              if self.author   else None)
        add(key="fields",      value=self.dictify_list(self.fields) if self.fields   else None)

        add(key="image",       value=self.image)

        return data


class EmbedAuthor:
    """https://docs.discord.com/developers/developer-tools/embedded-app-sdk#embedauthor"""
    def __init__(self, name: str | None = None, url: str | None = None, icon_url: str | None = None, proxy_icon_url: str | None = None) -> None:
        self.name           = name
        self.url            = url
        self.icon_url       = icon_url
        self.proxy_icon_url = proxy_icon_url
        pass

    def to_dict(self) -> dict[str, str | None]:
        data = {}

        def add(key,value):
            if value:
                data[key] = value

        add(key="name",           value=self.name,)
        add(key="url",            value=self.url,)
        add(key="icon_url",       value=self.icon_url,)
        add(key="proxy_icon_url", value=self.proxy_icon_url)
    
        return data


class EmbedProvider:
    """
        https://docs.discord.com/developers/developer-tools/embedded-app-sdk#embedprovider
        Doesn't seem to do much    
    """
    def __init__(self, name: str | None = None, url: str | None = None) -> None:
        self.name = name
        self.url  = url
        pass

    def to_dict(self) -> dict[str, str | None]:
        data = {}

        def add(key,value):
            if value:
                data[key] = value
        
        add(key="name", value=self.name)
        add(key="url",  value=self.url)
        
        return data

class EmbedFooter:
    """https://docs.discord.com/developers/developer-tools/embedded-app-sdk#embedfooter"""
    def __init__(self, text: str, icon_url: str | None = None, proxy_icon_url: str | None = None) -> None:
        self.text           = text
        self.icon_url       = icon_url
        self.proxy_icon_url = proxy_icon_url
        pass

    def to_dict(self) -> dict[str, str | None]:
        data = {}

        def add(key,value):
            if value:
                data[key] = value

        add(key="text",           value=self.text)
        add(key="icon_url",       value=self.icon_url)
        add(key="proxy_icon_url", value=self.proxy_icon_url)
        
        return data

class EmbedField:
    """https://docs.discord.com/developers/developer-tools/embedded-app-sdk#embedfooter"""
    def __init__(self, name: str, value: str, inline: bool) -> None:
        self.name   = name
        self.value  = value
        self.inline = inline
        pass

    def to_dict(self) -> dict[str, str | bool]:
        data = {}

        def add(key,value):
            if value:
                data[key] = value
        
        add(key="name",   value=self.name)
        add(key="value",  value=self.value)
        add(key="inline", value=self.inline)

        return data
from django import template
from django.template.base import NodeList, Parser, TextNode, Token
from django.template.context import Context
from django.template.exceptions import TemplateSyntaxError

from clx.app.scripts import SCRIPT_TAG

register = template.Library()


class ScriptNode(template.Node):
    """Renders nothing: the body ships in the compiled bundle."""

    def render(self, context: Context) -> str:
        return ""


@register.tag("script")
def script(parser: Parser, token: Token) -> ScriptNode:
    """Mark a block of JavaScript for the compiled bundle."""
    nodelist: NodeList = parser.parse(("endscript",))
    parser.delete_first_token()

    parts = []
    for node in nodelist:
        if not isinstance(node, TextNode):
            raise TemplateSyntaxError(
                "{% script %} takes literal JavaScript. Pass template values "
                "as data attributes and read them in init()."
            )
        parts.append(node.s)

    body = "".join(parts)
    if not SCRIPT_TAG.match(body):
        raise TemplateSyntaxError(
            "{% script %} content must be wrapped in <script> tags."
        )

    return ScriptNode()

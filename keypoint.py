#!/usr/bin/env python

from fpdf import FPDF
from HTMLParser import HTMLParser
from tidylib import tidy_document
import re
import sys
import yaml
import yaml.constructor
import itertools

try:
    # included in standard lib from Python 2.7
    from collections import OrderedDict
except ImportError:
    # try importing the backported drop-in replacement
    # it's available on PyPI
    from ordereddict import OrderedDict

def pairwise(iterable):
    "s -> (s0,s1), (s1,s2), (s2, s3), ..."
    a, b = itertools.tee(iterable)
    next(b, None)
    return itertools.izip_longest(a, b)

class OrderedDictYAMLLoader(yaml.Loader):
    """
    A YAML loader that loads mappings into ordered dictionaries.
    """

    def __init__(self, *args, **kwargs):
        yaml.Loader.__init__(self, *args, **kwargs)

        self.add_constructor(u'tag:yaml.org,2002:map', type(self).construct_yaml_map)
        self.add_constructor(u'tag:yaml.org,2002:omap', type(self).construct_yaml_map)

    def construct_yaml_map(self, node):
        data = OrderedDict()
        yield data
        value = self.construct_mapping(node)
        data.update(value)

    def construct_mapping(self, node, deep=False):
        if isinstance(node, yaml.MappingNode):
            self.flatten_mapping(node)
        else:
            raise yaml.constructor.ConstructorError(None, None,
                'expected a mapping node, but found %s' % node.id, node.start_mark)

        mapping = OrderedDict()
        for key_node, value_node in node.value:
            key = self.construct_object(key_node, deep=deep)
            try:
                hash(key)
            except TypeError, exc:
                raise yaml.constructor.ConstructorError('while constructing a mapping',
                    node.start_mark, 'found unacceptable key (%s)' % exc, key_node.start_mark)
            value = self.construct_object(value_node, deep=deep)
            mapping[key] = value
        return mapping

ribbon_theme = {
    "lmargin-slide": 30,
    "tmargin-slide": 45,
    "body-font": "PT Sans",
    "body-color": (0, 0, 0),
    "title-font": "PT Sans",
    "title-color": (100, 100, 100),
    "title-style": "B",
    "title-size": 40,
    "bullet-font": "DejaVuSans",
    "bullet-color": (180, 180, 180),
    "bullet-size": 20,
    "para-size": 20,
    "l0-size": 20,
    "l1-size": 18,
    "l2-size": 16,
    "ln-size": 16,
    "l0-bullet": unichr(0x2022),
    "l1-bullet": unichr(0x2043),
    "l2-bullet": unichr(0x2022),
    "ln-bullet": unichr(0x2043),
    "para-height": 10,
    "l0-height": 10,
    "l1-height": 9,
    "l2-height": 8,
    "ln-height": 8,
    "para-space-before": 15,
    "l0-space-before": 15,
    "l1-space-before": 11,
    "l2-space-before": 8,
    "ln-space-before": 8,
    "image-space-before": 10,
}

class FormatError(Exception):
    pass

class Element(object):
    def __init__(self, pdf, h):
        self.pdf = pdf
        self.h = h
        self.style = set()

    def __notify_style_changed(self):
        self.style_changed("".join(self.style))

    def start_strong(self):
        self.style.add("B")
        self.__notify_style_changed()

    def end_strong(self):
        self.style.remove("B")
        self.__notify_style_changed()

    def write(self, text):
        self.pdf.write(self.h, text)

    def end(self):
        pass

class Para(Element):
    def __init__(self, pdf):
        Element.__init__(self, pdf, pdf.theme["para-height"])
        self.pdf.set_text_color(*self.pdf.theme["body-color"])
        self.pdf.set_font(self.pdf.theme["body-font"], '',
                          self.pdf.theme["para-size"])

        if not self.pdf.check_page_start():
            self.pdf.ln(self.pdf.theme["para-space-before"])

    def style_changed(self, style):
        self.pdf.set_font(self.pdf.theme["body-font"], style,
                          self.pdf.theme["para-size"])

    def end(self):
        self.pdf.ln(0.01)

class BaseImage(Element):
    def __init__(self, pdf, src, width, height):
        Element.__init__(self, pdf, 0)
        self.src = src
        self.width = width / 72.0 * 25.4
        self.height = height / 72.0 * 25.4

class CenterImage(BaseImage):
    def __init__(self, pdf, src, width, height):
        BaseImage.__init__(self, pdf, src, width, height)

        hspace = self.pdf.w - self.pdf.r_margin - self.pdf.l_margin
        hpad = (hspace - self.width) / 2
        left = self.pdf.l_margin + hpad

        self.pdf.ln(self.pdf.theme["image-space-before"])
        self.pdf.image(self.src, left, self.pdf.y, self.width, self.height)

        info = self.pdf.images[self.src]

        if self.height == 0:
            self.height = self.width * info["h"] / info["w"]
        
        self.pdf.set_y(self.pdf.y + self.height)

class FloatImage(BaseImage):
    def __init__(self, pdf, src, width, height):
        BaseImage.__init__(self, pdf, src, width, height)
        self.pdf.set_image(self)
        self.draw()

    def draw(self):
        img_margin = self.pdf.theme["lmargin-slide"]
        pad = 15
        self.pdf.set_left_margin(img_margin + self.width + pad)
        print "Set Left Margin:", self.pdf.l_margin
        self.pdf.image(self.src, img_margin, self.pdf.t_margin,
                       self.width, self.height)

    def write(self, text):
        pass

class List(Element):
    def __init__(self, pdf, bullet, parent=None):
        self.pdf = pdf
        self.bullet = bullet
        self.parent = parent
        self.bullet_margin = None
        self.nitem = 1

        if self.parent == None:
            self.level = 0
        else:
            self.level = self.parent.level + 1

        Element.__init__(self, pdf, self.__get_height())

    def __get_theme_param(self, param):
        try:
            return self.pdf.theme[param % self.level]
        except KeyError:
            return self.pdf.theme[param % "n"]

    def __get_height(self):
        return self.__get_theme_param("l%s-height")

    def __get_font_size(self):
        return self.__get_theme_param("l%s-size")

    def __get_space_before(self):
        return self.__get_theme_param("l%s-space-before")

    def __get_bullet(self):
        if self.bullet == "1":
            font_size = self.__get_font_size()
            self.pdf.set_font(self.pdf.theme["body-font"], '', font_size)            
            return "%d.  " % self.nitem
        elif self.bullet == "*":
            bullet = self.__get_theme_param("l%s-bullet")
            self.pdf.set_font(self.pdf.theme["bullet-font"], '',
                              self.pdf.theme["bullet-size"])
            return "%s  " % bullet
        else:
            raise ValueError("invalid bullet type")

    def style_changed(self, style):
        self.pdf.set_font(self.pdf.theme["body-font"], style,
                          self.__get_font_size())

    def start_item(self):
        if not self.pdf.check_page_start():
            self.pdf.ln(self.__get_space_before())

        bullet = self.__get_bullet()
        # Get bullet width including margins
        blt_width = self.pdf.get_string_width(bullet)

        # Output bullet
        self.pdf.set_text_color(*self.pdf.theme["bullet-color"])
        self.pdf.cell(blt_width, self.__get_height(), bullet, 0, 0, '')

        # Setup for Text
        font_size = self.__get_font_size()
        self.pdf.set_font(self.pdf.theme["body-font"], '', font_size)
        self.pdf.set_text_color(*self.pdf.theme["body-color"])

        # Save left margin
        self.bullet_margin = self.pdf.l_margin
        self.pdf.set_left_margin(self.bullet_margin + blt_width)

        self.nitem += 1

    def end_item(self):
        self.pdf.set_left_margin(self.bullet_margin)
        self.pdf.ln(0.01)

    def end_list(self):
        return self.parent

class PDF(FPDF):
    def __init__(self, theme):
        FPDF.__init__(self, orientation="L")
        self.theme = theme
        self.set_margins(self.theme["lmargin-slide"],
                         self.theme["tmargin-slide"])
        self.img = None
        self.page_start_flag = True
        
    def header(self):
        self.image('ribbon.png', 250, 0, 15)
        self.set_text_color(*self.theme["title-color"])
        self.set_font(self.theme["title-font"],
                      self.theme["title-style"],
                      self.theme["title-size"])
        
        self.text(30, 30, self.title)
        self.page_start_flag = True

        if self.img:
            self.img.draw()

    def check_page_start(self):
        if not self.page_start_flag:
            return False

        ret = self.get_y() == self.t_margin
        if ret == True:
            self.page_start_flag = False
            return True

    def footer(self):
        self.set_y(-15)
        self.set_font('Arial', 'I', 8)
        self.cell(0, 10, 'Page '+ str(self.page_no())+'/{nb}', 0, 0, 'C')

    def set_title(self, title):
        self.title = title

    def set_image(self, img):
        self.img = img

class GenSlideDeck(object):
    def __init__(self, slides, pdf):
        self.pdf = pdf
        self.slides = slides
        self.content = []
        self.element = None
        self.list = None
        self.layout = None
        self.__gen_slides()

    def __new_slide(self, title):
        self.pdf.set_title(title)
        self.pdf.set_margins(self.pdf.theme["lmargin-slide"],
                             self.pdf.theme["tmargin-slide"])
        self.pdf.set_image(None)
        self.pdf.add_page()
        self.pdf.set_title("%s (Contd)" % title)
        self.list = None
        self.layout = None

    def __gen_item(self, item, next_item):
        if isinstance(item, list):
            self.__gen_list(item)
        else:
            self.list.start_item()
            self.list.write(item)

        if not isinstance(next_item, list):
            self.list.end_item()

    def __gen_list(self, items):
        self.list = List(self.pdf, "*", self.list)

        for item, next_item in pairwise(items):
            self.__gen_item(item, next_item)

        self.list = self.list.end_list()

    def __gen_image(self, image):
        try:
            src = image["src"]
        except KeyError:
            raise FormatError("Missing src for image")
        width = image.get("width", 0)
        height = image.get("height", 0)
        CenterImage(self.pdf, src, width, height)

    def __gen_layout(self, layout):
        pass

    def __gen_table(self, table):
        pass

    def __gen_one_slide(self, title, body):
        self.__new_slide(title)
        if isinstance(body[0], dict):
            dtype = body[0].get("type", None)
            if dtype == "image":
                self.__gen_image(dtype)
            elif dtype == "layout":
                self.__gen_layout(dtype)
            elif dtype == "table":
                self.__gen_table(dtype)
            else:
                raise FormatError("Unknown data type: %s", dtype)
        else:
            self.__gen_list(body)

    def __gen_slides(self):
        for title, body in self.slides.iteritems():
            self.__gen_one_slide(title, body)

    def handle_starttag(self, tag, attrs):
        self.content = []

        if tag == "ul":
            self.list = List(self.pdf, "*", self.list)
        elif tag == "ol":
            self.list = List(self.pdf, "1", self.list)
        elif tag == "li":
            self.list.start_item()
            self.element = self.list
        elif tag == "p":
            self.element = Para(self.pdf)
        elif tag == "strong":
            self.element.start_strong()
        elif tag == "img":
            attrs = dict(attrs)
            width = int(attrs.get("width", 0))
            height = int(attrs.get("height", 0))
            align = attrs.get("align", None)
            src = attrs["src"]
            if align:
                FloatImage(self.pdf, src, width, height)
            else:
                CenterImage(self.pdf, src, width, height)
        else:
            self.hidden = True

    def whitespace_cleanup(self, content):
        # print "!" + content + "!"
        content = content.split("\n")
        content = " ".join(content)
        content = re.sub(r'(\s)+', r'\1', content) 
        # print "@" + content + "@"
        return content
            
    def handle_endtag(self, tag):
        content = "".join(self.content)
        content = self.whitespace_cleanup(content)

        if tag == "h2":
            self.pdf.set_title(content)
            self.pdf.set_margins(self.pdf.theme["lmargin-slide"],
                                 self.pdf.theme["tmargin-slide"])
            self.pdf.set_image(None)
            self.pdf.add_page()
            self.pdf.set_title("%s (Contd)" % content)
            print "Title:", content
        elif tag == "li":
            self.list.end_item()
            self.element = None
        elif tag in ("ul", "ol"):
            self.list = self.list.end_list()
        elif tag == "p":
            self.element.end()
            self.element = None
        elif tag == "strong":
            self.element.end_strong()

    def handle_data(self, data):
        if self.element == None:
            self.content.append(data)
        else:
            data = self.whitespace_cleanup(data)
            self.element.write(data)

pdf = PDF(ribbon_theme)
pdf.add_font("PT Sans", "B", "/home/vijaykumar/Dropbox/ascii-slides/PTS75F.ttf", uni=True)
pdf.add_font("PT Sans", "", "/home/vijaykumar/Dropbox/ascii-slides/PTS55F.ttf", uni=True)
pdf.add_font("DejaVuSans", "", "/home/vijaykumar/Dropbox/ascii-slides/DejaVuSans.ttf", uni=True)
pdf.alias_nb_pages()

fp = open(sys.argv[1])
slides = yaml.load(fp, Loader=OrderedDictYAMLLoader)
GenSlideDeck(slides, pdf)
pdf.output(sys.argv[2],'F')

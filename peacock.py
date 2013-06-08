#!/usr/bin/env python

from fpdf import FPDF
from HTMLParser import HTMLParser
from tidylib import tidy_document

import fpdf
import re
import sys
import yaml
import yaml.constructor
import itertools
import os.path

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
    def __init__(self, theme, theme_dir):
        FPDF.__init__(self, orientation="L")
        self.theme = theme
        self.theme_dir = theme_dir
        self.set_margins(self.theme["lmargin-slide"],
                         self.theme["tmargin-slide"])
        self.img = None
        self.page_start_flag = True

    def theme_file(self, filename):
        return os.path.join(self.theme_dir, filename)
        
    def header(self):
        draw_slide_background = self.theme.get("slide-background", "")
        exec(draw_slide_background, { "pdf": self })
        
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

class Layout(object):
    def start(self, pos):
        raise NotImplementedError("start() not implemented")

    def end(self):
        raise NotImplementedError("end() not implemented")

class SimpleLayout(object):
    def __init__(self, pdf):
        self.pdf = pdf
    
    def start(self, pos):
        pass
    
    def end(self):
        pass

class TwoColumnLayout(object):
    def __init__(self, pdf):
        self.pdf = pdf
        self.column_gap = self.pdf.theme["lmargin-slide"]
        available = self.pdf.w - (self.pdf.theme["lmargin-slide"] * 2)
        available -=  self.column_gap
        self.column_width = available / 2
        self.done = None

    def __get_col_margin(self):
        return (self.pdf.theme["lmargin-slide"]
                + self.column_width
                + self.column_gap)

    def __start_left(self):
        rmargin = self.__get_col_margin()
        self.pdf.set_margins(self.pdf.theme["lmargin-slide"],
                             self.pdf.theme["tmargin-slide"],
                             rmargin)
        self.done = "left"
        self.pdf.set_xy(self.pdf.l_margin, self.pdf.t_margin)

    def __start_right(self):
        lmargin = self.__get_col_margin()
        self.pdf.set_margins(lmargin,
                             self.pdf.theme["tmargin-slide"],
                             self.pdf.theme["lmargin-slide"])
        self.done = "right"
        self.pdf.set_xy(self.pdf.l_margin, self.pdf.t_margin)

    def __start_auto(self):
        if self.done == "left":
            self.__start_right()
        elif self.done == "right":
            self.__start_left()
        else: # is None
            self.__start_left()
        
    def start(self, pos):
        if pos == "left":
            self.__start_left()
        elif pos == "right":
            self.__start_right()
        elif pos == None:
            self.__start_auto()
        else:
            ValueError("invalid position '%s'" % pos)

    def end(self):
        pass

class GenSlideDeck(object):
    def __init__(self, slides, pdf, rpath):
        self.pdf = pdf
        self.slides = slides
        self.rpath = rpath
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
        self.layout = SimpleLayout(self.pdf)

    def __gen_item(self, item, next_item):
        if isinstance(item, list):
            self.__gen_list(item)
        else:
            self.list.start_item()
            self.list.write(item)

        if not isinstance(next_item, list):
            self.list.end_item()

    def __gen_list(self, items):
        self.layout.start(None)
        self.list = List(self.pdf, "*", self.list)

        for item, next_item in pairwise(items):
            self.__gen_item(item, next_item)

        self.list = self.list.end_list()
        self.layout.end()

    def __gen_image(self, image):
        try:
            src = image["src"]
        except KeyError:
            raise FormatError("Missing src for image")
        
        if not os.path.isabs(src):
            src = os.path.join(self.rpath, src)
            
        width = image.get("width", 0)
        height = image.get("height", 0)
        pos = image.get("pos", None)
        
        self.layout.start(pos)
        CenterImage(self.pdf, src, width, height)
        self.layout.end()

    def __gen_layout(self, layout):
        layout_mode = layout.get("mode", None)
        if layout_mode == None:
            raise FormatError("Missing layout mode")
        
        if layout_mode == "two-col":
            self.layout = TwoColumnLayout(self.pdf)
        elif layout_mode == "simple":
            self.layout = SimpleLayout(self.pdf)
        else:
            raise FormatError("Invalid layout mode '%s'", layout["mode"])

    def __gen_table(self, table):
        pass

    def __gen_one_slide(self, title, body):
        self.__new_slide(title)
        
        for i, item in enumerate(body):
            if isinstance(item, dict):
                dtype = item.get("type", None)
                if dtype == "image":
                    self.__gen_image(item)
                elif dtype == "layout":
                    self.__gen_layout(item)
                elif dtype == "table":
                    self.__gen_table(item)
                elif dtype == None:
                    raise FormatError("Missing data type")
                else:
                    raise FormatError("Unknown data type: %s", dtype)
            else:
                self.__gen_list(body[i:])
                break

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

def usage(msg=None):
    sys.stderr.write(msg)
    print "Usage: peacock <input-file> <theme-dir> <output-file>"
    if msg != None: exit(1)

def peacock(in_fname, theme_dir, out_fname):
    fpdf.set_global("FPDF_FONT_DIR", theme_dir)
    fp = open(os.path.join(theme_dir, "info.yaml"))
    theme = yaml.load(fp)

    pdf = PDF(theme, theme_dir)
    pdf.alias_nb_pages()

    for font in theme.get("fonts", []):
        name = font[0]
        style = font[1]
        font_file = os.path.join(theme_dir, font[2])
        pdf.add_font(name, style, font_file, uni=True)
    
    fp = open(in_fname)
    slides = yaml.load(fp, Loader=OrderedDictYAMLLoader)
    GenSlideDeck(slides, pdf, os.path.dirname(in_fname))
    pdf.output(out_fname, 'F')

if __name__ == "__main__":
    if len(sys.argv) != 4:
        usage("error: insufficient arguments")

    peacock(sys.argv[1], sys.argv[2], sys.argv[3])

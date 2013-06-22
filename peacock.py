#!/usr/bin/env python

from fpdf import FPDF

import fpdf
import re
import sys
import yaml
import yaml.constructor
import itertools
import os.path
import pygments
import pygments.util
import pygments.lexers
import pygments.styles

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

class ThemeError(Exception):
    pass

class Para(object):
    def __init__(self, pdf):
        self.pdf = pdf
        self.pdf.set_text_color(*self.pdf.theme["l0-color"])
        self.pdf.set_font(*self.pdf.theme["l0-font"])

    def style_changed(self, style):
        self.pdf.set_font(self.pdf.theme["body-font"], style,
                          self.pdf.theme["l0-size"])

    def end(self):
        self.pdf.ln(0.01)

class BaseImage(object):
    def __init__(self, pdf, src, width, height):
        self.pdf = pdf
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

class Code(object):
    def __init__(self, pdf, code, lexer):
        self.pdf = pdf
        fname, fstyle, fsize = self.pdf.theme["code-font"]

        self.pdf.set_font(fname, fstyle, fsize)
        style = pygments.styles.get_style_by_name("emacs")
        style = dict(style)
        for token, text in pygments.lex(code["code"], lexer):
            token_style = style[token]

            if token_style["color"]:
                r, g, b = map(ord, token_style["color"].decode("hex"))
            else:
                r, g, b = (0, 0, 0)
            self.pdf.set_text_color(r, g, b)

            if token_style["bold"] and token_style["italic"]:
                self.pdf.set_font(fname, "BI", fsize)
            elif token_style["bold"]:
                self.pdf.set_font(fname, "B", fsize)
            elif token_style["italic"]:
                self.pdf.set_font(fname, "I", fsize)
            else:
                self.pdf.set_font(fname, "", fsize)

            height = pdf.theme["code-height"]
            self.pdf.write(height, text)

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

class List(object):
    def __init__(self, pdf, bullet, nitems, parent=None):
        self.pdf = pdf
        self.bullet = bullet
        self.parent = parent
        self.bullet_margin = None
        self.nitems = nitems
        self.icount = 1

        if self.parent == None:
            self.level = 0
        else:
            self.level = self.parent.level + 1

    def __get_theme_param(self, param):
        try:
            return self.pdf.theme[param % self.level]
        except KeyError:
            return self.pdf.theme[param % "n"]

    def __get_height(self):
        return self.__get_theme_param("l%s-height")

    def __get_font(self):
        return self.__get_theme_param("l%s-font")

    def __get_space_before(self):
        return self.__get_theme_param("l%s-space-before")

    def __get_color(self):
        return self.__get_theme_param("l%s-color")

    def __get_bullet(self):
        if self.bullet == "1":
            font_size = self.__get_font_size()
            self.pdf.set_font(self.pdf.theme["body-font"], '', font_size)            
            return "%d.  " % self.icount
        elif self.bullet == "*":
            bullet = self.__get_theme_param("l%s-bullet")
            self.pdf.set_font(*self.pdf.theme["bullet-font"])
            return "%s  " % bullet
        else:
            raise ValueError("invalid bullet type")

    def style_changed(self, style):
        self.pdf.set_font(self.pdf.theme["body-font"], style,
                          self.__get_font_size())

    def start_item(self, first):
        if not first:
            self.pdf.ln(self.__get_space_before())

        if self.nitems == 1:
            self.pdf.set_font(*self.__get_font())
            self.pdf.set_text_color(*self.__get_color())
            return
            
        bullet = self.__get_bullet()
        # Get bullet width including margins
        blt_width = self.pdf.get_string_width(bullet)

        # Output bullet
        self.pdf.set_text_color(*self.pdf.theme["bullet-color"])
        self.pdf.cell(blt_width, self.__get_height(), bullet, 0, 0, '')

        # Setup for Text
        self.pdf.set_font(*self.__get_font())
        self.pdf.set_text_color(*self.__get_color())

        # Save left margin
        self.bullet_margin = self.pdf.l_margin
        self.pdf.set_left_margin(self.bullet_margin + blt_width)

        self.icount += 1

    def end_item(self):
        self.pdf.set_left_margin(self.bullet_margin)
        self.pdf.ln(0.01)

    def end_list(self):
        return self.parent

    def write(self, text):
        height = self.__get_height()
        self.pdf.write(height, text)

class PDF(FPDF):
    def __init__(self, theme, theme_dir):
        FPDF.__init__(self, orientation="L")
        self.theme = theme
        self.theme_dir = theme_dir
        self.set_margins(self.theme["lmargin-slide"],
                         self.theme["tmargin-slide"])
        self.img = None
        self.slide_title = None

    def theme_file(self, filename):
        return os.path.join(self.theme_dir, filename)
        
    def header(self):
        draw_slide_background = self.theme.get("slide-background", "")
        exec(draw_slide_background, { "pdf": self })

        if self.slide_title:
            self.set_text_color(*self.theme["slide-title-color"])
            self.set_font(*self.theme["slide-title-font"])
        
            self.text(30, 30, self.slide_title)
            
        if self.img:
            self.img.draw()

    def footer(self):
        self.set_y(-15)
        self.set_font('Arial', 'I', 8)
        self.cell(0, 10, 'Page '+ str(self.page_no())+'/{nb}', 0, 0, 'C')

    def set_slide_title(self, title):
        self.slide_title = title

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

class Renderer(object):
    def __init__(self, pdf, rpath):
        self.pdf = pdf
        self.slides = None
        self.rpath = rpath

    def __box_text(self, box, text):
        (box_x, box_y, box_w, box_h), box_align, box_font, (box_color) = box

        self.pdf.set_xy(box_x, box_y)
        self.pdf.set_font(*box_font)
        self.pdf.set_text_color(*box_color)
        self.pdf.cell(box_w, box_h, txt=text, align=box_align)

    def render_title(self, meta):
        self.pdf.add_page()
        self.__box_text(self.pdf.theme["title-box"], meta["title"])
        self.__box_text(self.pdf.theme["author-box"], meta["author"])
        self.__box_text(self.pdf.theme["email-box"], meta["email"])

    def render_section(self):
        pass

    def render_slideset(self, slideset):
        self.slides = slideset
        self.list = None
        self.layout = None
        self.__gen_slides()

    def __new_slide(self, title):
        self.pdf.set_slide_title(title)
        self.pdf.set_margins(self.pdf.theme["lmargin-slide"],
                             self.pdf.theme["tmargin-slide"])
        self.pdf.set_image(None)
        self.pdf.add_page()
        self.pdf.set_slide_title("%s (Contd)" % title)
        self.list = None
        self.layout = SimpleLayout(self.pdf)

    def __gen_item(self, i, item, next_item):
        if isinstance(item, list):
            self.__gen_list(item)
        else:
            self.list.start_item(i == 0)
            self.list.write(item)

        if not isinstance(next_item, list):
            self.list.end_item()

    def __gen_list(self, items):
        self.layout.start(None)
        self.list = List(self.pdf, "*", len(items), self.list)

        for i, (item, next_item) in enumerate(pairwise(items)):
            self.__gen_item(i, item, next_item)

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

    def __gen_code(self, code):
        if not "code" in code:
            raise FormatError("Missing 'code' in 'code'")

        lang = code.get("lang", "text")
        try:
            lexer = pygments.lexers.get_lexer_by_name(lang)
        except pygments.util.ClassNotFound:
            raise FormatError("Unknown 'lang' '%s'" % lang)

        pos = code.get("pos", None)

        self.layout.start(pos)
        Code(self.pdf, code, lexer)
        self.layout.end()

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
                elif dtype == "code":
                    self.__gen_code(item)
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

def error(msg):
    sys.stderr.write("peacock: ")
    sys.stderr.write(msg)
    sys.stderr.write("\n")
    exit(1)

class Peacock(object):
    def __init__(self):
        self.infname = None
        self.outfname = None
        self.theme_dir = None
        self.theme = None
        self.pdf = None
        self.meta = None
        self.slideset = None

    def main(self, infname, outfname, theme_dir):
        self.infname = infname
        self.outfname = outfname
        self.theme_dir = theme_dir

        self.init_theme()
        self.pdf = PDF(self.theme, self.theme_dir)
        self.pdf.alias_nb_pages()
        self.init_theme_fonts()
        self.init_presentation()
        self.init_pdf_metainfo()
        self.render()

    def render(self):
        renderer = Renderer(self.pdf, os.path.dirname(self.infname))
        renderer.render_title(self.meta)
        renderer.render_slideset(self.slideset)
        self.pdf.output(self.outfname, 'F')

    def init_presentation(self):
        try:
            with open(self.infname) as fp:
                pt = yaml.load_all(fp, Loader=OrderedDictYAMLLoader)
                self.meta = pt.next()
                self.slideset = pt.next()
        except IOError as e:
            raise FormatError("error opening file '%s': %s" % (self.infname, e))
        except yaml.MarkedYAMLError as e:
            raise FormatError("error parsing '%s': %s" % (self.infname, e))

    def init_pdf_metainfo(self):
        self.meta = dict(self.meta)
        
        if "title" not in self.meta or not isinstance(self.meta["title"], str):
            raise FormatError("'title' not present or is incorrect type")

        if "author" not in self.meta or not isinstance(self.meta["author"], str):
            raise FormatError("'author' not present or is incorrect type")

        if "keywords" not in self.meta or not isinstance(self.meta["keywords"], list):
            raise FormatError("'keywords' not present or is incorrect type")

        for keyword in self.meta["keywords"]:
            if not isinstance(keyword, str):
                raise FormatError("'keywords' should contain only strings")

        self.pdf.set_title(self.meta["title"])
        self.pdf.set_author(self.meta["author"])
        keywords = ", ".join(self.meta.get("keywords", []))
        self.pdf.set_keywords(keywords)
        self.pdf.set_creator("peacock")

    def init_theme(self):
        try:
            info_fname = os.path.join(self.theme_dir, "info.yaml")
            with open(info_fname) as fp:
                self.theme = yaml.load(fp)
        except IOError as e:
            raise ThemeError("error opening file: %s" % e)
        except yaml.MarkedYAMLError as e:
            raise ThemeError("error parsing '%s': %s" % (info_fname, e))

    def init_theme_fonts(self):
        fpdf.set_global("FPDF_FONT_DIR", self.theme_dir)

        for finfo in self.theme.get("fonts", []):
            try:
                name, style, fname = finfo
            except ValueError:
                raise ThemeError("invalid 'fonts' in theme, fmt: [ name, style, fname ]")

            if style not in [ "B", "I", "BI", "IB", "" ]:
                raise ThemeError("invalid style in 'fonts' - '%s'" % style)

            fname = os.path.join(self.theme_dir, fname)
            if not os.path.exists(fname):
                raise ThemeError("font file '%s' not found" % fname)

            self.pdf.add_font(name, style, fname, uni=True)

def usage(msg=None):
    sys.stderr.write(msg)
    print "Usage: peacock <input-file> <theme-dir> <output-file>"
    if msg != None: exit(1)

if __name__ == "__main__":
    if len(sys.argv) != 4:
        usage("error: insufficient arguments\n")

    try:
        peacock = Peacock()
        peacock.main(sys.argv[1], sys.argv[2], sys.argv[3])
    except FormatError as e:
        error(str(e))
    except ThemeError as e:
        error(str(e))


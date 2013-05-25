#!/usr/bin/env python

from fpdf import FPDF
from HTMLParser import HTMLParser
from tidylib import tidy_document
import re
import sys

ribbon_theme = {
    "font": "PT Sans",
    "bullet-font": "DejaVuSans",
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
}

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

class Para(Element):
    def __init__(self, pdf):
        Element.__init__(self, pdf, pdf.theme["para-height"])
        self.pdf.set_text_color(0)
        self.pdf.set_font(self.pdf.theme["font"], '',
                          self.pdf.theme["para-size"])
        self.pdf.ln(self.pdf.theme["para-space-before"])

    def style_changed(self, style):
        print style
        self.pdf.set_font(self.pdf.theme["font"], style,
                          self.pdf.theme["para-size"])

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
            self.pdf.set_font(self.pdf.theme["font"], '', font_size)            
            return "%d.  " % self.nitem
        elif self.bullet == "*":
            bullet = self.__get_theme_param("l%s-bullet")
            self.pdf.set_font(self.pdf.theme["bullet-font"], '',
                              self.pdf.theme["bullet-size"])
            return "%s  " % bullet
        else:
            raise ValueError("invalid bullet type")

    def style_changed(self, style):
        self.pdf.set_font(self.pdf.theme["font"], style,
                          self.__get_font_size())

    def start_item(self):
        self.pdf.ln(self.__get_space_before())

        bullet = self.__get_bullet()
        # Get bullet width including margins
        blt_width = self.pdf.get_string_width(bullet)

        # Output bullet
        self.pdf.set_text_color(180)
        self.pdf.cell(blt_width, self.__get_height(), bullet, 0, 0, '')

        # Setup for Text
        font_size = self.__get_font_size()
        self.pdf.set_font(self.pdf.theme["font"], '', font_size)
        self.pdf.set_text_color(0)

        # Save left margin
        self.bullet_margin = self.pdf.l_margin
        self.pdf.set_left_margin(self.bullet_margin + blt_width)
        # print self.l_margin

        self.nitem += 1

    def end_item(self):
        self.pdf.set_left_margin(self.bullet_margin)

    def end_list(self):
        return self.parent

class PDF(FPDF):
    def set_theme(self, theme):
        self.theme = theme
        
    def header(self):
        self.image('ribbon.png', 250, 0, 15)
        self.set_text_color(100)
        self.set_font('PT Sans', 'B', 40)
        self.cell(0, 10, self.title)
        self.ln(10)

    def footer(self):
        self.set_y(-15)
        self.set_font('Arial', 'I', 8)
        self.cell(0, 10, 'Page '+ str(self.page_no())+'/{nb}', 0, 0, 'C')

    def set_title(self, title):
        self.title = title

class MyHTMLParser(HTMLParser):
    def __init__(self, pdf):
        HTMLParser.__init__(self)
        self.pdf = pdf
        self.content = []
        self.element = None
        self.list = None

    def handle_starttag(self, tag, attrs):
        self.content = []

        if tag == "ul":
            self.element = self.list = List(self.pdf, "*", self.list)
        elif tag == "ol":
            self.element = self.list = List(self.pdf, "1", self.list)
        elif tag == "li":
            self.list.start_item()
        elif tag == "p":
            self.element = Para(self.pdf)
        elif tag == "strong":
            self.element.start_strong()
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
            self.pdf.add_page()
            self.pdf.set_title("%s (Contd)" % content)
        elif tag == "li":
            self.list.end_item()
        elif tag in ("ul", "ol"):
            self.element = self.list = self.list.end_list()
        elif tag == "p":
            self.element = None
        elif tag == "strong":
            self.element.end_strong()

    def handle_data(self, data):
        if self.element == None:
            self.content.append(data)
        else:
            data = self.whitespace_cleanup(data)
            self.element.write(data)

pdf = PDF(orientation="L")
pdf.set_theme(ribbon_theme)
pdf.add_font("PT Sans", "B", "/home/vijaykumar/Dropbox/ascii-slides/PTS75F.ttf", uni=True)
pdf.add_font("PT Sans", "", "/home/vijaykumar/Dropbox/ascii-slides/PTS55F.ttf", uni=True)
pdf.add_font("DejaVuSans", "", "/home/vijaykumar/Dropbox/ascii-slides/DejaVuSans.ttf", uni=True)
pdf.set_margins(30, 30)
pdf.alias_nb_pages()

fp = open(sys.argv[1])
html = fp.read()
fp.close()

parser = MyHTMLParser(pdf)
parser.feed(html)

pdf.output(sys.argv[2],'F')

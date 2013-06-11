# Peacock

Peacock generates a PDF presentation from a text input file 
represented in YAML.

## Dependencies

  * pyfpdf - Simple PDF generation for Python
  * pyyaml - YAML implementation in Python

## Installing

TBD

## Command Usage

The general syntax for invoking peacock

    peacock.py <input-file> <output-file> <theme-dir>

## Input File Format

Smaller presentations require atleast two YAML documents, in the input
file. The first document contains meta information about the
document. The second document contains the information for a slide
set.

### Meta Information

The meta information is a YAML map, that has the following keys:

  * `title` - the title of the presentation
  * `author` - the presenter's name
  * `email` - the presenter's email address
  * `date` - date of creation, yyyy-mm-dd. Optional
  * `keywords` - YAML list of keywords associated with the
    document. Optional

The meta information is used to generate the title slide (to
implemented yet) and inject meta information into the PDF file.

### Slide Set

The slide set is a YAML map, that maps slide title to slide
contents. The slide contents is a YAML list.

In the simplest case each item in the list could be strings, in which
case the the items are rendered as a bulleted list.
%.html: %.txt
	asciidoc -f html4.conf -b html4 $<

%.tidy: %.html
	-tidy $< > $@

%.pdf: %.tidy 
	./keypoint.py $< $@
all: zfssend

zfssend: main.go
	go build -ldflags -s -o $@ $<

install: zfssend
	$(INSTALL) -o 0 -g 0 -m 755 zfssend $(DESTDIR)/usr/local/sbin/


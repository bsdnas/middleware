# $FreeBSD$

PORTNAME=	freenas-migrate93
PORTVERSION=	2023042100
CATEGORIES=	freenas
VALID_CATEGORIES+=	freenas

MAINTAINER=	dev@ixsystems.com
COMMENT=	Tool to upgrade from 9.X databases

RUN_DEPENDS=	python>0:${PORTSDIR}/lang/python \
		${PYTHON_PKGNAMEPREFIX}lxml>0:devel/py-lxml

USES=		python
USE_GITHUB=	yes
GH_ACCOUNT=	freenas
GH_TAGNAME=	0687ad0af8
EXTRA_PATCHES=	${PATCHDIR}/add-tn-13.3-files:-p0

NO_BUILD=	yes

.include <bsd.port.pre.mk>

do-install:
	${MKDIR} ${STAGEDIR}${PREFIX}/lib/migrate93
	cd ${WRKSRC} && ${COPYTREE_SHARE} src ${STAGEDIR}${PREFIX}/lib/migrate93/
	cd ${WRKSRC} && ${COPYTREE_SHARE} freenasUI ${STAGEDIR}${PREFIX}/lib/migrate93/
	cd ${WRKSRC} && ${COPYTREE_SHARE} django ${STAGEDIR}${PREFIX}/lib/migrate93/
	cd ${WRKSRC} && ${COPYTREE_SHARE} south ${STAGEDIR}${PREFIX}/lib/migrate93/
	${SED} -e "s,/usr/lib/,/usr/local/lib/,g" -e "s,/usr/bin/,/usr/local/bin/,g" \
		${WRKSRC}/sbin/migrate93 > ${STAGEDIR}${PREFIX}/sbin/migrate93
	${CHMOD} a+x ${STAGEDIR}${PREFIX}/sbin/migrate93
	(cd ${STAGEDIR}${PREFIX}/lib/migrate93; ${FIND} . -type f ! -name '*.orig' \
		| ${SED} -e 's,^\./,,g' \
		| ${AWK} '{print length, $$0}' | ${SORT} -rn \
		| ${AWK} '{print "lib/migrate93/"$$2 }' >> ${TMPPLIST})

.include <bsd.port.post.mk>

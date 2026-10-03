# Health-only image for the first safe deploy (issue #519): busybox httpd
# serving one file, so GET /health answers 200 "ok". No engine, no secret,
# nothing written at run time.
FROM busybox:1.37
RUN mkdir -p /www && printf 'ok\n' > /www/health
EXPOSE 8080
CMD ["httpd", "-f", "-p", "8080", "-h", "/www"]

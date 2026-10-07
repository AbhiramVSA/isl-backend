# LiveKit for Railway. Railway has no public UDP, so WebRTC media goes over
# ICE-TCP through a Railway TCP proxy. The proxy's public port is assigned by
# Railway and differs from the port it forwards to, so start.sh advertises the
# public port and socat bridges the forwarded port onto it.
FROM livekit/livekit-server:latest AS livekit

FROM alpine:3.20
RUN apk add --no-cache socat bind-tools
COPY --from=livekit /livekit-server /usr/local/bin/livekit-server
COPY start.sh /start.sh
RUN chmod +x /start.sh
EXPOSE 7880 7881
CMD ["/start.sh"]

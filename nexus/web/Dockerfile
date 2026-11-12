FROM node:22-alpine
WORKDIR /app
COPY package*.json ./
RUN npm ci
COPY . .
ARG NEXT_PUBLIC_NEXUS_API=http://localhost:8000
ENV NEXT_PUBLIC_NEXUS_API=$NEXT_PUBLIC_NEXUS_API
RUN npm run build
EXPOSE 3000
CMD ["npm", "start"]

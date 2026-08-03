import express from 'express';
import cors from 'cors';
import cookieParser from 'cookie-parser';
import path from 'path';
import authRoutes from './routes/auth.routes';
import projectRoutes from './routes/project.routes';
import knowledgeRoutes from './routes/knowledge.routes';
import modelProviderRoutes from './routes/model-provider.routes';
import modelConfigRoutes from './routes/model-config.routes';
import swaggerUi from 'swagger-ui-express';
import { specs } from './swagger';

const app = express();

app.use(cors({
  origin: true, // Allow all origins for dev, restrict in prod
  credentials: true,
}));
app.use(express.json());
app.use(cookieParser());

// Docs
app.use('/api-docs', swaggerUi.serve, swaggerUi.setup(specs));

// Routes
app.use('/api/auth', authRoutes);
app.use('/api/projects', projectRoutes);
app.use('/api/projects/:id/model-config', modelConfigRoutes);
app.use('/api/knowledge', knowledgeRoutes);
app.use('/api/model-providers', modelProviderRoutes);

// Health check
app.get('/health', (req, res) => {
  res.status(200).json({ status: 'ok' });
});

// Serve static files if configured
if (process.env.SERVE_STATIC) {
  const staticPath = process.env.STATIC_PATH || path.join(__dirname, '../../client');
  console.log(`Serving static files from ${staticPath}`);
  
  app.use(express.static(staticPath));
  
  // Handle SPA routing - return index.html for all non-API routes
  app.get('*', (req, res, next) => {
    if (req.path.startsWith('/api')) {
      return next();
    }
    res.sendFile(path.join(staticPath, 'index.html'));
  });
}

export default app;

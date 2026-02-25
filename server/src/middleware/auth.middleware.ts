import { Request, Response, NextFunction } from 'express';
import jwt from 'jsonwebtoken';
import prisma from '../prisma';

const JWT_SECRET = process.env.JWT_SECRET || 'secret';

export interface AuthRequest extends Request {
  user?: {
    id: string;
    username: string;
  };
}

export const authenticateToken = async (req: AuthRequest, res: Response, next: NextFunction) => {
  const token = req.cookies.token || req.headers['authorization']?.split(' ')[1];

  if (!token) {
    return res.status(401).json({ code: 401, message: 'Unauthorized' });
  }

  try {
    const user = jwt.verify(token, JWT_SECRET) as { id: string; username: string };
    const existingUser = await prisma.user.findUnique({ where: { id: user.id } });
    if (!existingUser) {
      res.clearCookie('token');
      return res.status(401).json({ code: 401, message: 'User not found' });
    }
    req.user = { id: existingUser.id, username: existingUser.username };
    return next();
  } catch (err) {
    return res.status(403).json({ code: 403, message: 'Invalid token' });
  }
};

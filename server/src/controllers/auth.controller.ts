import { Request, Response } from 'express';
import bcrypt from 'bcryptjs';
import jwt from 'jsonwebtoken';
import prisma from '../prisma';
import { AuthRequest } from '../middleware/auth.middleware';

const JWT_SECRET = process.env.JWT_SECRET || 'secret';

export const register = async (req: Request, res: Response) => {
  try {
    const { username, password } = req.body;
    console.log('Register attempt:', { username }); // Add logging

    if (!username || !password) {
      return res.status(400).json({ message: 'Username and password are required' });
    }

    // Check if prisma client is working
    try {
      const existingUser = await prisma.user.findUnique({ where: { username } });
      if (existingUser) {
        return res.status(409).json({ message: 'Username already exists' });
      }
    } catch (dbError) {
      console.error('Database error during user lookup:', dbError);
      return res.status(500).json({ message: 'Database error', details: dbError });
    }

    const hashedPassword = await bcrypt.hash(password, 10);
    
    try {
      const user = await prisma.user.create({
        data: {
          username,
          password: hashedPassword,
        },
      });
      res.status(201).json({ message: 'User created successfully', userId: user.id });
    } catch (createError) {
      console.error('Database error during user creation:', createError);
      return res.status(500).json({ message: 'Failed to create user', details: createError });
    }
    
  } catch (error) {
    console.error('Register error:', error);
    res.status(500).json({ message: 'Internal server error', error: String(error) });
  }
};

export const login = async (req: Request, res: Response) => {
  try {
    const { username, password } = req.body;
    const user = await prisma.user.findUnique({ where: { username } });

    if (!user) {
      return res.status(404).json({ code: 404, message: '账号不存在', action: '立即注册' });
    }

    const isValid = await bcrypt.compare(password, user.password);
    if (!isValid) {
      return res.status(401).json({ code: 401, message: '密码错误' });
    }

    await prisma.user.update({
      where: { id: user.id },
      data: { last_login: new Date() },
    });

    const token = jwt.sign({ id: user.id, username: user.username }, JWT_SECRET, { expiresIn: '24h' });

    res.cookie('token', token, {
      httpOnly: true,
      secure: false, // process.env.NODE_ENV === 'production',
      maxAge: 24 * 60 * 60 * 1000,
    });

    res.json({ code: 200, message: 'Login successful', token, user: { id: user.id, username: user.username } });
  } catch (error) {
    res.status(500).json({ message: 'Internal server error' });
  }
};

export const me = async (req: AuthRequest, res: Response) => {
  if (!req.user) {
    return res.status(401).json({ code: 401, message: 'Not authenticated' });
  }
  res.json({ code: 200, user: req.user });
};

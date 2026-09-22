import React, { useEffect } from 'react';
import { useSelector } from 'react-redux';
import { useLocation, useNavigate } from 'react-router-dom';
import { RagChat } from '../components/ragChat/RagChat';

export const RagChatView = () => {
  const token = useSelector((state) => state.auth.token);
  const location = useLocation();
  const navigate = useNavigate();

  // Chat requires login (backend rejects anonymous sessions).
  useEffect(() => {
    if (!token) {
      navigate('/login', {
        state: {
          from: location.pathname,
        },
      });
    }
  }, [token, location.pathname, navigate]);

  if (!token) return null;

  return (
    <div className="pt3 pb5">
      <RagChat />
    </div>
  );
};

import React from 'react';
import { useIntl } from 'react-intl';
import { Button } from '../button';

export const ChatInput = ({
  value,
  onChange,
  onSubmit,
  loading,
  disabled,
  maxChars = 4000,
  placeholderId = 'rag.chat.placeholder',
  defaultPlaceholder = 'Ask TMBot about task states, permissions, workflows…',
  testIdInput = 'rag-input',
  testIdSend = 'rag-send',
}) => {
  const intl = useIntl();
  return (
    <form onSubmit={onSubmit} className="pa3 bt b--light-gray bg-white flex gap-2">
      <input
        type="text"
        value={value}
        onChange={(e) => onChange(e.target.value)}
        placeholder={intl.formatMessage({
          id: placeholderId,
          defaultMessage: defaultPlaceholder,
        })}
        className="flex-auto pa3 br2 ba b--moon-gray f6"
        data-testid={testIdInput}
        maxLength={maxChars}
        disabled={loading || disabled}
      />
      <Button
        type="submit"
        className="bg-red white ph4"
        disabled={loading || !value.trim() || disabled}
        data-testid={testIdSend}
      >
        {loading ? '...' : 'Send'}
      </Button>
    </form>
  );
};

import { Box, Center, Checkbox, Flex } from '@mantine/core';
import { flexRender } from '@tanstack/react-table';
import { useCallback } from 'react';

const CustomTableHeader = ({
  getHeaderGroups,
  allRowIds,
  selectedTableIds,
  headerCellRenderFns,
  onSelectAllChange,
  tableCellProps,
}) => {
  const renderHeaderCell = (header) => {
    if (headerCellRenderFns[header.id]) {
      return headerCellRenderFns[header.id](header);
    }

    switch (header.id) {
      case 'select':
        return (
          <Center style={{ width: '100%' }}>
            <Checkbox
              size="xs"
              checked={
                allRowIds.length == 0
                  ? false
                  : selectedTableIds.length == allRowIds.length
              }
              indeterminate={
                selectedTableIds.length > 0 &&
                selectedTableIds.length !== allRowIds.length
              }
              onChange={onSelectAllChange}
            />
          </Center>
        );

      default:
        return flexRender(header.column.columnDef.header, header.getContext());
    }
  };

  return (
    <Box
      className="thead"
      style={{
        position: 'sticky',
        top: 0,
        backgroundColor: '#3E3E45',
        zIndex: 10,
      }}
    >
      {getHeaderGroups().map((headerGroup) => (
        <Box
          className="tr"
          key={headerGroup.id}
          style={{ display: 'flex', width: '100%' }}
        >
          {headerGroup.headers.map((header) => {
            return (
              <Box
                className="th"
                key={header.id}
                style={{
                  flex: header.column.columnDef.size
                    ? `0 0 ${header.getSize()}px`
                    : '1 1 0%',
                  width: header.column.columnDef.size
                    ? `${header.getSize()}px`
                    : 'auto',
                  maxWidth: header.column.columnDef.size
                    ? `${header.getSize()}px`
                    : 'none',
                  minWidth: header.column.columnDef.minSize
                    ? `${header.column.columnDef.minSize}px`
                    : '0px',
                  position: 'relative',
                  // ...(tableCellProps && tableCellProps({ cell: header })),
                }}
              >
                <Flex
                  align="center"
                  style={{
                    ...(header.column.columnDef.style &&
                      header.column.columnDef.style),
                    height: '100%',
                    paddingRight: header.column.getCanResize() ? '8px' : '0px', // Add padding for resize handle
                  }}
                >
                  {renderHeaderCell(header)}
                </Flex>
                {header.column.getCanResize() && (
                  <div
                    onMouseDown={header.getResizeHandler()}
                    onTouchStart={header.getResizeHandler()}
                    className={`resizer ${
                      header.column.getIsResizing() ? 'isResizing' : ''
                    }`}
                    style={{
                      position: 'absolute',
                      right: 0,
                      top: 0,
                      height: '100%',
                      width: '8px', // Make it slightly wider
                      cursor: 'col-resize',
                      userSelect: 'none',
                      touchAction: 'none',
                      backgroundColor: header.column.getIsResizing()
                        ? '#3b82f6'
                        : 'transparent',
                      opacity: header.column.getIsResizing() ? 1 : 0.3, // Make it more visible by default
                      transition: 'opacity 0.2s',
                      zIndex: 1000, // Ensure it's on top
                    }}
                    onMouseEnter={(e) => {
                      e.target.style.opacity = '1';
                      e.target.style.backgroundColor = '#6b7280';
                    }}
                    onMouseLeave={(e) => {
                      if (!header.column.getIsResizing()) {
                        e.target.style.opacity = '0.5';
                        e.target.style.backgroundColor = 'transparent';
                      }
                    }}
                  />
                )}
              </Box>
            );
          })}
        </Box>
      ))}
    </Box>
  );
};

export default CustomTableHeader;

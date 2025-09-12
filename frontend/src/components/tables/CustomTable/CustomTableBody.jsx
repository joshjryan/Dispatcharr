import { Box, Flex } from '@mantine/core';
import { VariableSizeList as List } from 'react-window';
import AutoSizer from 'react-virtualized-auto-sizer';
import table from '../../../helpers/table';

const CustomTableBody = ({
  getRowModel,
  expandedRowIds,
  expandedRowRenderer,
  renderBodyCell,
  getExpandedRowHeight,
  getRowStyles, // Add this prop to receive row styles
  tableBodyProps,
  tableCellProps,
}) => {
  const renderExpandedRow = (row) => {
    if (expandedRowRenderer) {
      return expandedRowRenderer({ row });
    }

    return <></>;
  };

  const rows = getRowModel().rows;

  const renderTableBodyContents = () => {
    const virtualized = false;

    if (virtualized) {
      return (
        <Box
          className="tbody"
          style={{ flex: 1, ...(tableBodyProps && tableBodyProps()) }}
        >
          <AutoSizer disableWidth>
            {({ height }) => {
              const getItemSize = (index) => {
                const row = rows[index];
                const isExpanded = expandedRowIds.includes(row.original.id);
                console.log(isExpanded);

                // Default row height
                let rowHeight = 28;

                if (isExpanded && getExpandedRowHeight) {
                  // If row is expanded, adjust the height to be larger (based on your logic)
                  // You can get this height from your state, or calculate based on number of items in the expanded row
                  rowHeight += getExpandedRowHeight(row); // This function would calculate the expanded row's height
                }

                return rowHeight;
              };

              return (
                <List
                  height={height}
                  itemCount={rows.length}
                  itemSize={getItemSize}
                  width="100%"
                  overscanCount={10}
                >
                  {({ index, style }) => {
                    const row = rows[index];
                    return renderTableBodyRow(row, index, style);
                  }}
                </List>
              );
            }}
          </AutoSizer>
        </Box>
      );
    }

    return (
      <Box className="tbody" style={{ flex: 1 }}>
        {rows.map((row, index) => renderTableBodyRow(row, index))}
      </Box>
    );
  };

  const renderTableBodyRow = (row, index, style = {}) => {
    // Get custom styles for this row if the function exists
    const customRowStyles = getRowStyles ? getRowStyles(row) : {};

    // Extract any className from customRowStyles
    const customClassName = customRowStyles.className || '';
    delete customRowStyles.className; // Remove from object so it doesn't get applied as inline style

    return (
      <Box style={style} key={`row-${row.id}`}>
        <Box
          key={`tr-${row.id}`}
          className={`tr ${index % 2 == 0 ? 'tr-even' : 'tr-odd'} ${customClassName}`}
          style={{
            display: 'flex',
            width: '100%',
            ...(row.getIsSelected() && {
              backgroundColor: '#163632',
            }),
            ...customRowStyles, // Apply the remaining custom styles here
          }}
        >
          {row.getVisibleCells().map((cell) => {
            return (
              <Box
                className="td"
                key={`td-${cell.id}`}
                style={{
                  flex: cell.column.columnDef.size
                    ? `0 0 ${cell.column.getSize()}px`
                    : '1 1 0%',
                  width: cell.column.columnDef.size
                    ? `${cell.column.getSize()}px`
                    : 'auto',
                  maxWidth: cell.column.columnDef.size
                    ? `${cell.column.getSize()}px`
                    : 'none',
                  minWidth: cell.column.columnDef.minSize
                    ? `${cell.column.columnDef.minSize}px`
                    : '0px',
                  ...(tableCellProps && tableCellProps({ cell })),
                }}
              >
                <Flex align="center" style={{ height: '100%' }}>
                  {renderBodyCell({ row, cell })}
                </Flex>
              </Box>
            );
          })}
        </Box>
        {expandedRowIds.includes(row.original.id) && renderExpandedRow(row)}
      </Box>
    );
  };

  return renderTableBodyContents();
};

export default CustomTableBody;

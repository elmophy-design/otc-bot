"""Global Error Handling Middleware"""
import traceback
from ..utils.logger import get_logger

logger = get_logger(__name__)

class ErrorHandler:
    """Professional Error Handler"""
    
    async def handle_error(self, update, context):
        """Handle errors gracefully"""
        error = context.error
        logger.error(f"Error: {error}\n{traceback.format_exc()}")
        
        try:
            if update and update.callback_query:
                await update.callback_query.answer(
                    "⚠️ An error occurred. Please try again.",
                    show_alert=True
                )
        except Exception:
            pass
        
        return True
